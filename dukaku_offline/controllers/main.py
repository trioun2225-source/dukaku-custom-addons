import json
import logging

from odoo import fields, http
from odoo.http import request
from odoo.tools import file_open
from odoo.addons.point_of_sale.controllers.main import PosController

from ..models.offline_operation import OfflineOperationRejected

_logger = logging.getLogger(__name__)


# ── Service-worker override ───────────────────────────────────────────────────
# Replace the stock helper so /pos/service-worker.js serves our enhanced SW.
# The route method (pos_web_service_worker) stays on PosController unchanged;
# only the body it reads is replaced.

def _dukaku_get_pos_service_worker(self):
    with file_open('dukaku_offline/static/src/app/service_worker.js') as f:
        return f.read()


PosController._get_pos_service_worker = _dukaku_get_pos_service_worker


# ── Manifest controller ───────────────────────────────────────────────────────

class DukakuOfflineController(http.Controller):

    @http.route('/pos/manifest.json', type='http', auth='public', methods=['GET'])
    def pos_manifest(self, config_id=None, **kwargs):
        """Return a Web App Manifest scoped to the given POS config.

        The <link rel="manifest"> in the POS template passes config_id as a
        query parameter so each POS config gets its own start_url — no
        hardcoding in any tracked file, and multi-tenant safe.
        """
        if not config_id:
            return request.make_response('config_id required', status=400)

        try:
            cid = int(config_id)
        except (ValueError, TypeError):
            return request.make_response('invalid config_id', status=400)

        # start_url must be the exact URL the SW has in its cache.
        # _get_url_to_cache() caches "/pos/ui/{id}" (no query string), so
        # start_url must match that string character-for-character.
        # The ?from_backend=True variant is cached separately and must NOT
        # be used here — it changes the JS boot context.
        start_url = f'/pos/ui/{cid}'

        manifest = {
            'id': f'/pos/ui/{cid}',
            'name': 'Dukaku POS',
            'short_name': 'Dukaku',
            'description': 'Dukaku Point of Sale',
            'start_url': start_url,
            'scope': '/pos/',
            'display': 'standalone',
            'orientation': 'any',
            'theme_color': '#1A1A1A',
            'background_color': '#1A1A1A',
            'icons': [
                {
                    'src': '/dukaku_offline/static/src/img/icon-192.png',
                    'sizes': '192x192',
                    'type': 'image/png',
                    'purpose': 'any',
                },
                {
                    'src': '/dukaku_offline/static/src/img/icon-512.png',
                    'sizes': '512x512',
                    'type': 'image/png',
                    'purpose': 'any',
                },
                {
                    'src': '/dukaku_offline/static/src/img/icon-512-maskable.png',
                    'sizes': '512x512',
                    'type': 'image/png',
                    'purpose': 'maskable',
                },
            ],
        }

        return request.make_response(
            json.dumps(manifest, indent=2),
            headers=[
                ('Content-Type', 'application/manifest+json'),
                # no-store: the SW is not supposed to cache this; the browser
                # fetches it once for install and re-checks it in background.
                ('Cache-Control', 'no-store'),
            ],
        )

    # ── Generic offline-operation synchronization endpoint ────────────────────
    # auth='user': a normal authenticated Odoo session is required - never
    # public. The acting user for every operation in the batch is always
    # request.env.user; no field in `operations` is ever read as a user
    # identity ("never trust a client-provided user_id" is satisfied by
    # construction: there is nothing here that reads one).
    @http.route('/dukaku_offline/submit_operations', type='jsonrpc', auth='user')
    def submit_operations(self, operations=None, **kw):
        if not operations or not isinstance(operations, list):
            return {'results': []}

        # Deterministic ordering within one device's queue; operation_uid
        # remains the actual idempotency key regardless of order.
        ordered = sorted(
            operations,
            key=lambda o: (str(o.get('device_uid') or ''), _safe_int(o.get('client_seq'), 0)),
        )
        # Streams a terminal rejection has blocked, scoped to THIS batch
        # only - this in-memory set itself is never persisted and never
        # affects a later, separate submission's OWN fresh operations.
        # Each individual operation actually skipped because of it,
        # however, still gets its own normal persisted terminal
        # DEPENDENT_STREAM_BLOCKED row (Stage 8A UID-determinism fix) -
        # only the "was S already blocked in this batch" bookkeeping is
        # batch-local and disposable, never the canonical outcome of any
        # one operation_uid.
        blocked_streams = set()
        return {
            'results': [_process_one_operation(request.env, op, blocked_streams) for op in ordered]
        }


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _operation_response(rec, is_duplicate):
    return {
        'operation_uid': rec.operation_uid,
        'status': rec.status,  # canonical: 'accepted' or 'rejected', never 'duplicate'/'error'
        'is_duplicate': is_duplicate,
        'reason_code': rec.reason_code or None,
        'reason_message': rec.reason_message or None,
        'result': rec.result_payload or {},
    }


def _reject_without_row(operation_uid, reason_code, reason_message, is_duplicate=False):
    """A rejection that is never persisted as its own operation row - used
    only for envelope-level validation failures (malformed UID, missing
    required fields, an unrelated create failure) and the cross-user
    UID_CONFLICT case, none of which represent a business fact this
    operation_uid's OWN submitter should own a canonical outcome for. A
    later resubmission of the same operation_uid by its rightful owner is
    therefore processed completely fresh.

    A dependent-stream skip is NOT handled here as of the Stage 8A UID-
    determinism fix - it must receive a normal, persisted, terminal
    canonical row (see the DEPENDENT_STREAM_BLOCKED handling below),
    because one operation_uid must correspond to exactly one canonical
    server outcome within the server idempotency-retention window, not a
    transient in-batch skip that a later, separate submission could
    re-litigate. (A row is only eligible for cleanup after the 90-day
    terminal-operation retention period - see
    _cron_cleanup_terminal_operations() - after which a resubmission of
    the same operation_uid is no longer recognized at all, a documented
    V1 limitation, not a second canonical outcome for a live row.)
    """
    return {
        'operation_uid': operation_uid, 'status': 'rejected', 'is_duplicate': is_duplicate,
        'reason_code': reason_code, 'reason_message': reason_message, 'result': {},
    }


def _process_one_operation(env, op, blocked_streams):
    """Process a single queued operation. Never raises - every outcome
    (malformed input, unknown type, duplicate, dependent-stream-blocked,
    rejection, unexpected/retryable failure, success) returns a
    structured result so a batch never aborts on one bad entry.
    """
    Operation = env['dukaku.offline.operation'].sudo()
    Registry = env['dukaku.offline.handler.registry']
    user = env.user

    operation_uid = str(op.get('operation_uid') or '').strip()
    device_uid = str(op.get('device_uid') or '').strip()
    operation_type = str(op.get('operation_type') or '').strip()
    client_seq = _safe_int(op.get('client_seq'), 0)
    payload = op.get('payload') or {}
    occurred_at_client = op.get('occurred_at_client') or None

    if not Operation.is_valid_operation_uid(operation_uid):
        return _reject_without_row(operation_uid, 'MALFORMED_UID', "Malformed operation UID.")
    if not device_uid or not operation_type:
        return _reject_without_row(
            operation_uid, 'VALIDATION_ERROR', "device_uid and operation_type are required."
        )

    # ── Duplicate/resume lookup: security-sensitive ─────────────────────────
    # Actor ownership is checked BEFORE any stored result is ever returned or
    # any processing resumed. device_uid is deliberately not treated as
    # authentication for this check - only submitted_by_user_id (server-
    # derived, never client-supplied) decides who may see/resume it.
    rec = Operation.search([('operation_uid', '=', operation_uid)], limit=1)
    if rec:
        if rec.submitted_by_user_id.id != user.id:
            return _reject_without_row(
                operation_uid, 'UID_CONFLICT', "This operation could not be processed.",
                is_duplicate=True,
            )
        if rec.status != 'pending':
            # Terminal - replay the canonical stored result. Never
            # re-executed, and never affected by this batch's stream
            # blocking (that only applies to operations actually
            # attempted in THIS submission).
            return _operation_response(rec, is_duplicate=True)
        # status == 'pending': an earlier attempt hit an UNEXPECTED
        # failure and left this row non-terminal. Resume processing on
        # the SAME row rather than creating a second one.
    else:
        # ── Dependent-stream check (only for genuinely fresh operations) ───
        # The generic layer treats the key purely as an opaque string; it
        # never derives or trusts one from the client - only from the
        # registry, which resolves it server-side from the validated
        # payload/target (Stage 8A §4). Evaluated BEFORE create only to
        # decide whether the row about to be created will be dispatched -
        # a blocked stream still gets its own normal canonical row below
        # (Stage 8A UID-determinism fix): one operation_uid must resolve
        # to exactly one canonical server outcome, and a skip that left no
        # row behind would let a later, separate submission of the same
        # UID execute for real - two histories for one UID, which is
        # exactly the invariant this fix closes.
        stream_key = Registry._get_offline_stream_key(env, operation_type, payload)
        dependent_blocked = stream_key is not None and stream_key in blocked_streams

        now = fields.Datetime.now()
        # ── Race-safe idempotent create ─────────────────────────────────────
        # The unique() SQL constraint, not this search-then-create, is the
        # final authority: a concurrent duplicate INSERT blocks on the index
        # and either fails (loser re-fetches the winner's row below) or
        # succeeds (winner) - there is no window where two rows for the same
        # UID both exist.
        try:
            with env.cr.savepoint():
                rec = Operation.create({
                    'operation_uid': operation_uid,
                    'device_uid': device_uid,
                    'client_seq': client_seq,
                    'operation_type': operation_type,
                    'payload': payload,
                    'submitted_by_user_id': user.id,
                    'submission_company_id': user.company_id.id,
                    'occurred_at_client': occurred_at_client,
                    'received_at': now,
                    'status': 'pending',
                })
        except Exception:
            rec = Operation.search([('operation_uid', '=', operation_uid)], limit=1)
            if not rec:
                # Not a UID collision - a genuine, unrelated create failure.
                return _reject_without_row(
                    operation_uid, 'VALIDATION_ERROR', "Could not record this operation."
                )
            if rec.submitted_by_user_id.id != user.id:
                return _reject_without_row(
                    operation_uid, 'UID_CONFLICT', "This operation could not be processed.",
                    is_duplicate=True,
                )
            if rec.status != 'pending':
                return _operation_response(rec, is_duplicate=True)
            # else: the concurrent winner also left it pending (raced into
            # an unexpected failure itself) - fall through and resume.

        if dependent_blocked:
            # Terminal canonical rejection - never dispatched, never
            # mutates the business target, never creates a vertical
            # event. Also blocks any LATER stream member in this same
            # batch, exactly like a handler-raised rejection would.
            rec.write({
                'status': 'rejected', 'processed_at': fields.Datetime.now(),
                'reason_code': 'DEPENDENT_STREAM_BLOCKED',
                'reason_message':
                    "Skipped: an earlier operation in this batch for the same target was rejected.",
            })
            blocked_streams.add(stream_key)
            return _operation_response(rec, is_duplicate=False)

    # ── Closed, database-registry-aware handler dispatch ────────────────────
    handlers = Registry._get_offline_handlers()
    handler = handlers.get(operation_type)
    if handler is None:
        rec.write({
            'status': 'rejected', 'processed_at': fields.Datetime.now(),
            'reason_code': 'UNKNOWN_OPERATION',
            'reason_message': f"Unknown operation type: {operation_type}",
        })
        return _operation_response(rec, is_duplicate=False)

    stream_key = Registry._get_offline_stream_key(env, operation_type, payload)

    # The handler runs under the AUTHENTICATED user's own env, never sudo -
    # every existing ACL/record-rule/_ensure_authorized() check in whatever
    # business method it calls applies exactly as it would for any other
    # request. Only the bookkeeping row above is ever sudo'd.
    try:
        with env.cr.savepoint():
            result = handler(env, payload) or {}
    except OfflineOperationRejected as exc:
        # Expected business failure - terminal, persisted, replayable.
        rec.write({
            'status': 'rejected', 'processed_at': fields.Datetime.now(),
            'reason_code': exc.reason_code, 'reason_message': exc.message,
            'result_payload': exc.snapshot or {},
        })
        if stream_key is not None:
            blocked_streams.add(stream_key)
        return _operation_response(rec, is_duplicate=False)
    except Exception as exc:  # noqa: BLE001
        # UNEXPECTED failure (programming error, transient DB/runtime
        # issue, anything the handler didn't classify itself). The
        # savepoint above has already rolled back any partial business
        # mutation. This must NOT become a false terminal business
        # result: the row stays 'pending' (not written to accepted/
        # rejected), so the same operation_uid can be safely resubmitted
        # and re-enter processing above. No traceback reaches the client;
        # the full traceback is logged server-side only, and a short,
        # non-sensitive note is kept on the row for diagnostics.
        _logger.exception(
            "Unexpected error processing offline operation %s (%s) - left pending, retryable",
            operation_uid, operation_type,
        )
        rec.write({
            'retry_count': rec.retry_count + 1,
            'last_error': (str(exc) or exc.__class__.__name__)[:500],
        })
        return {
            'operation_uid': operation_uid, 'status': 'error', 'is_duplicate': False,
            'reason_code': 'TEMPORARY_ERROR',
            'reason_message': "A temporary error occurred; this operation can be safely retried.",
            'result': {},
        }

    rec.write({
        'status': 'accepted', 'processed_at': fields.Datetime.now(),
        'result_payload': result,
    })
    return _operation_response(rec, is_duplicate=False)
