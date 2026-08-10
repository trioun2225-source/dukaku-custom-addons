# -*- coding: utf-8 -*-
import re
from datetime import timedelta

from odoo import fields, models

_UID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,64}$")


class OfflineOperationRejected(Exception):
    """The only *expected*-failure exception type the generic dispatcher
    understands.

    A registered handler catches its own vertical-specific exceptions
    (AccessError, a workflow-specific UserError subclass, whatever) and
    re-raises this instead, choosing the reason_code itself - the generic
    layer has no vertical knowledge to classify a rejection correctly, so
    classification is deliberately pushed to whichever module understands
    its own exception semantics.

    `snapshot`: an optional, minimal, non-sensitive dict returned to the
    client alongside the rejection - ONLY for conflict classes where the
    target record was successfully resolved and is legitimately visible
    to the caller (STALE_STATE, LIFECYCLE_LOCKED). A handler must leave
    this None for anything access-related (NOT_AUTHORIZED,
    COMPANY_ACCESS_DENIED, TARGET_NOT_FOUND, UID_CONFLICT) - the generic
    layer does not enforce this by itself; it trusts the handler, which is
    the only party that knows whether the record was legitimately
    resolved at all.

    Any exception OTHER than this one raised by a handler is treated as
    unexpected (see the controller) - never silently reclassified as a
    business rejection.
    """

    def __init__(self, reason_code, message, snapshot=None):
        self.reason_code = reason_code
        self.message = message
        self.snapshot = snapshot
        super().__init__(message)


class DukakuOfflineHandlerRegistry(models.AbstractModel):
    """Registry-aware, per-database extension point for offline operation
    handlers - replaces a process-global Python dict.

    Odoo worker processes commonly host registries for several tenant
    databases with different installed modules in the same process. A
    plain module-level dict populated by decorator side effects at import
    time is process-global: once dukaku_dry_cleaning has been imported for
    ANY database in that process, its handlers would incorrectly appear
    available to every OTHER database in the same process too, regardless
    of whether that database actually has the module installed.

    _inherit is registry-native and per-database by construction instead:
    Odoo builds one distinct registry (and therefore one distinct model
    class MRO) per database. A database whose registry doesn't include
    dukaku_dry_cleaning's _inherit extension of this model simply never
    sees its handlers - there is nothing to leak, because the extended
    class itself does not exist in that database's registry.

    dukaku_offline never inherits/extends this with any dry_cleaning (or
    other vertical) entry - only vertical modules do that, from their own
    side, via normal Odoo _inherit.
    """

    _name = "dukaku.offline.handler.registry"
    _description = "Dukaku Offline Handler Registry"

    def _get_offline_handlers(self):
        """Return {operation_type: bound_handler(env, payload) -> dict}.

        Base implementation: empty. Each vertical module extends this via
        _inherit, calls super() first, and adds its own entries - so a
        handler dict is always the union of every installed vertical's
        contributions in THIS database's registry, never anything from a
        module that isn't installed here.
        """
        return {}

    def _get_offline_stream_key(self, env, operation_type, payload):
        """Return an opaque, server-derived stream/dependency key for
        ordering purposes (e.g. "dry_cleaning.ticket:42"), or None if this
        operation type doesn't participate in stream-based ordering.

        Verticals override this; the generic dispatcher only ever compares
        these as opaque strings - it never parses, interprets, or trusts a
        client-supplied value for this purpose. Must not raise - an
        unresolvable target here just means "no stream" (None); the
        handler itself will raise the appropriate rejection when actually
        dispatched.
        """
        return None


class DukakuOfflineOperation(models.Model):
    """Generic, vertical-agnostic synchronization inbox for offline-queued
    client operations.

    Contains zero references to any dry_cleaning (or other vertical) model
    by design - an operation is a record of *what the client requested*,
    never *what the authoritative server accepted as having happened*. That
    second thing is each vertical's own business method's job to record in
    its own audit model (e.g. dry_cleaning.event); this model only tracks
    the sync-envelope lifecycle around the call to that method. Structurally
    separate schemas, not a shared table with a flag, so a rejected or
    duplicate operation can never leave a trace in a vertical's own
    immutable history.

    No direct ORM access for ordinary users (see ir.model.access.csv) - all
    mutation happens through the submit_operations() controller under
    sudo(), which enforces user-ownership checks in Python before ever
    revealing a stored result (see the controller for why a record rule
    alone can't express that check). No business handler ever runs under
    sudo - only this bookkeeping row's own create()/write()/search() does.
    """

    _name = "dukaku.offline.operation"
    _description = "Dukaku Offline Operation"
    _order = "client_seq asc, id asc"

    operation_uid = fields.Char(
        required=True, copy=False, index=True,
        help="Client-generated UUIDv4 (or equivalent stable id), the actual "
             "idempotency key. Reused verbatim on every retry of the same "
             "operation.",
    )
    device_uid = fields.Char(required=True, copy=False)
    client_seq = fields.Integer(
        required=True, default=0,
        help="Monotonic per-device sequence number, for ordering only. "
             "Never compared across different devices - cross-device "
             "conflicts are resolved by authoritative server state, not by "
             "sequence value.",
    )
    operation_type = fields.Char(
        required=True, copy=False,
        help="Matched against the closed, database-registry-aware handler "
             "registry. Never used for dynamic model/method resolution.",
    )
    payload = fields.Json(help="Vertical-specific request arguments, read only by that vertical's own registered handler.")
    submitted_by_user_id = fields.Many2one(
        "res.users", required=True, readonly=True, copy=False,
        help="Populated exclusively from the authenticated request's own "
             "session (request.env.user) - never from a client-supplied "
             "field, which is never even read.",
    )
    submission_company_id = fields.Many2one(
        "res.company", required=True, readonly=True, copy=False,
        help="The authenticated user's own active company AT SUBMISSION "
             "TIME - submission context/diagnostics only. This is NOT "
             "necessarily the company of whatever record the operation "
             "targets, and it is never used to determine or expand access:"
             " existing record rules on the vertical's own target model "
             "remain the sole access-control authority regardless of this "
             "field's value.",
    )
    occurred_at_client = fields.Datetime(
        help="Non-authoritative: the operator's device-reported time. "
             "Diagnostics/reporting only - never used for event ordering, "
             "workflow authority, or any transition/authorization decision.",
    )
    received_at = fields.Datetime(required=True, readonly=True, copy=False)
    processed_at = fields.Datetime(readonly=True, copy=False)
    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
        ],
        required=True, default="pending", readonly=True, copy=False,
        help="Canonical STORED result. 'duplicate' is never a stored "
             "status - a retry of an already-resolved operation returns "
             "the original accepted/rejected outcome with a separate "
             "is_duplicate flag. A row can also stay 'pending' after an "
             "UNEXPECTED (non-business) failure - deliberately non-"
             "terminal, so the same operation_uid can be safely retried "
             "and re-enter processing rather than being permanently "
             "misclassified as a business rejection.",
    )
    reason_code = fields.Char(readonly=True, copy=False)
    reason_message = fields.Char(readonly=True, copy=False)
    result_payload = fields.Json(
        help="Generic structured result from the handler (e.g. an "
             "authoritative snapshot of whatever record the operation "
             "targeted). Never a Many2one/relational field to any "
             "vertical model - see the module-level docstring.",
    )
    retry_count = fields.Integer(
        default=0, readonly=True, copy=False,
        help="Incremented each time an unexpected (non-business) failure "
             "leaves this row pending and it is picked up again. "
             "Diagnostics only.",
    )
    last_error = fields.Char(
        readonly=True, copy=False,
        help="Short, non-traceback diagnostic note for the most recent "
             "unexpected failure, if any. Full tracebacks go to the server "
             "log only, never to this field or to any client response.",
    )

    _operation_uid_uniq = models.Constraint(
        "unique(operation_uid)",
        "This operation has already been received.",
    )

    @staticmethod
    def is_valid_operation_uid(value):
        return bool(value) and bool(_UID_RE.match(value))

    def _cron_cleanup_terminal_operations(self, retention_days=90):
        """Delete accepted/rejected rows older than retention_days.

        Pending rows are never touched regardless of age - only a
        terminal (accepted/rejected) row is eligible. A retry arriving
        after a row has been cleaned up is no longer recognized by UID -
        this is a documented, accepted V1 limitation (see completion
        report), not a bug: it only matters for a device that stayed
        offline longer than the retention window, and the worst case is a
        legitimate re-execution of a still-valid request, independently
        re-validated exactly as a first submission would be.
        """
        cutoff = fields.Datetime.now() - timedelta(days=retention_days)
        stale = self.sudo().search([
            ("status", "in", ["accepted", "rejected"]),
            ("received_at", "<", cutoff),
        ])
        stale.unlink()
