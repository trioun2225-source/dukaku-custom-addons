# -*- coding: utf-8 -*-
"""Stage 8/8A: generic dukaku.offline.operation model, database-registry-
aware handler registry, and the submit_operations() dispatch logic -
tested with zero dependency on any vertical module, proving dukaku_offline
installs and functions with dukaku_dry_cleaning (or anything else) absent.

The throwaway handlers used below live in offline_operation_test_support.py
(a real module file, gated on tools.config['test_enable']) rather than
being defined here - Odoo imports an addon's tests/ package strictly AFTER
that addon's own models have already been collected into the registry, so
a model class defined only in a test file is never incorporated into the
runtime class MRO. See that file's docstring for the full explanation.
"""
import threading
import uuid
from datetime import timedelta

import odoo
from psycopg2 import IntegrityError
from odoo.tests.common import TransactionCase, HttpCase, JsonRpcException
from odoo.tools import mute_logger

from odoo.addons.dukaku_offline.controllers.main import _process_one_operation
from odoo.addons.dukaku_offline.models.offline_operation_test_support import (
    TEST_ECHO_TYPE,
    TEST_REJECT_TYPE,
    TEST_REJECT_WITH_SNAPSHOT_TYPE,
    TEST_FLAKY_MUTATION_TYPE,
    TEST_STREAM_TYPE,
)


def _uid():
    return str(uuid.uuid4())


def _op(operation_type, operation_uid=None, device_uid="device-1", client_seq=1, payload=None, **extra):
    op = {
        "operation_uid": operation_uid or _uid(),
        "device_uid": device_uid,
        "client_seq": client_seq,
        "operation_type": operation_type,
        "payload": payload or {},
    }
    op.update(extra)
    return op


@odoo.tests.tagged("post_install", "-at_install")
class TestDukakuOfflineOperation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_user = cls.env["res.users"].create({
            "name": "Offline Test Other User",
            "login": "dukaku_offline_test_other_user",
            "group_ids": [(6, 0, cls.env.ref("base.group_user").ids)],
        })

    def _process(self, env, op, blocked_streams=None):
        return _process_one_operation(env, op, blocked_streams if blocked_streams is not None else set())

    # -- 1: DB-level uniqueness -------------------------------------------

    def test_01_operation_uid_unique_at_db_level(self):
        uid = _uid()
        Operation = self.env["dukaku.offline.operation"].sudo()
        Operation.create({
            "operation_uid": uid, "device_uid": "d1", "client_seq": 1,
            "operation_type": TEST_ECHO_TYPE, "submitted_by_user_id": self.env.user.id,
            "submission_company_id": self.env.company.id, "received_at": odoo.fields.Datetime.now(),
        })
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            Operation.create({
                "operation_uid": uid, "device_uid": "d2", "client_seq": 1,
                "operation_type": TEST_ECHO_TYPE, "submitted_by_user_id": self.env.user.id,
                "submission_company_id": self.env.company.id, "received_at": odoo.fields.Datetime.now(),
            })

    # -- 2-4: canonical accepted/rejected result on retry -------------------

    def test_02_duplicate_accepted_uid_returns_original_result(self):
        op = _op(TEST_ECHO_TYPE, payload={"x": 1})
        first = self._process(self.env, op)
        self.assertEqual(first["status"], "accepted")
        self.assertFalse(first["is_duplicate"])

        second = self._process(self.env, dict(op, payload={"x": 999}))
        self.assertEqual(second["status"], "accepted")
        self.assertTrue(second["is_duplicate"])
        self.assertEqual(second["result"], first["result"])
        self.assertEqual(second["result"]["echo"], {"x": 1})

    def test_03_duplicate_rejected_uid_returns_original_result(self):
        op = _op(TEST_REJECT_TYPE)
        first = self._process(self.env, op)
        self.assertEqual(first["status"], "rejected")
        self.assertEqual(first["reason_code"], "TEST_REASON")

        second = self._process(self.env, op)
        self.assertEqual(second["status"], "rejected")
        self.assertTrue(second["is_duplicate"])
        self.assertEqual(second["reason_code"], "TEST_REASON")

    def test_04_duplicate_status_never_becomes_a_third_canonical_value(self):
        op = _op(TEST_ECHO_TYPE)
        self._process(self.env, op)
        second = self._process(self.env, op)
        self.assertIn(second["status"], ("accepted", "rejected"))

    # -- 5: cross-user UID ownership -----------------------------------------

    def test_05_uid_owned_by_another_user_does_not_leak_result(self):
        op = _op(TEST_ECHO_TYPE, payload={"secret": "only for me"})
        self._process(self.env, op)

        other_env = self.env(user=self.other_user)
        result = self._process(other_env, op)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "UID_CONFLICT")
        self.assertEqual(result["result"], {})
        self.assertNotIn("secret", str(result))

    # -- 6: unknown operation type --------------------------------------------

    def test_06_unknown_operation_type_rejected_cleanly(self):
        result = self._process(self.env, _op("nonexistent.operation.type"))
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "UNKNOWN_OPERATION")

    # -- 7: no dry-cleaning (or any vertical) coupling ------------------------

    def test_07_generic_model_has_no_vertical_relationship_fields(self):
        Operation = self.env["dukaku.offline.operation"]
        for fname, field in Operation._fields.items():
            comodel = getattr(field, "comodel_name", None)
            if comodel:
                self.assertFalse(
                    comodel.startswith("dry_cleaning."),
                    f"dukaku.offline.operation.{fname} references {comodel} - "
                    "the generic model must have zero vertical model relationships.",
                )

    def test_07b_generic_controller_module_has_no_vertical_import(self):
        import odoo.addons.dukaku_offline.controllers.main as controller_mod
        source = open(controller_mod.__file__).read()
        self.assertNotIn("dry_cleaning", source)

    # -- 8-11: closed registry dispatch, no dynamic execution ----------------

    def test_08_closed_registry_dispatches_registered_handler(self):
        result = self._process(self.env, _op(TEST_ECHO_TYPE, payload={"a": "b"}))
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["result"]["echo"], {"a": "b"})

    def test_09_arbitrary_model_name_as_operation_type_cannot_be_dispatched(self):
        result = self._process(self.env, _op("res.users"))
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "UNKNOWN_OPERATION")

    def test_10_arbitrary_method_name_in_payload_is_inert(self):
        result = self._process(
            self.env, _op(TEST_ECHO_TYPE, payload={"method": "unlink", "model": "res.users"})
        )
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["result"]["echo"], {"method": "unlink", "model": "res.users"})
        self.assertTrue(self.env.user.exists())

    def test_11_arbitrary_field_dict_does_not_become_an_orm_write(self):
        target_name_before = self.env.user.name
        self._process(
            self.env, _op(TEST_ECHO_TYPE, payload={"name": "HACKED", "id": self.env.user.id})
        )
        self.assertEqual(self.env.user.name, target_name_before)

    # -- 12-13: user attribution ------------------------------------------

    def test_12_payload_user_id_is_ignored(self):
        op = _op(TEST_ECHO_TYPE, payload={"user_id": self.other_user.id})
        self._process(self.env, op)
        rec = self.env["dukaku.offline.operation"].sudo().search(
            [("operation_uid", "=", op["operation_uid"])]
        )
        self.assertEqual(rec.submitted_by_user_id, self.env.user)
        self.assertNotEqual(rec.submitted_by_user_id, self.other_user)

    def test_13_server_records_actual_authenticated_user(self):
        other_env = self.env(user=self.other_user)
        op = _op(TEST_ECHO_TYPE)
        self._process(other_env, op)
        rec = self.env["dukaku.offline.operation"].sudo().search(
            [("operation_uid", "=", op["operation_uid"])]
        )
        self.assertEqual(rec.submitted_by_user_id, self.other_user)

    # -- malformed input -------------------------------------------------

    def test_malformed_operation_uid_rejected(self):
        result = self._process(self.env, _op(TEST_ECHO_TYPE, operation_uid="not a uuid!!"))
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "MALFORMED_UID")

    def test_missing_device_uid_rejected(self):
        op = _op(TEST_ECHO_TYPE)
        op["device_uid"] = ""
        result = self._process(self.env, op)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "VALIDATION_ERROR")

    # -- retention ---------------------------------------------------------

    def test_retention_cleans_only_old_terminal_rows(self):
        Operation = self.env["dukaku.offline.operation"].sudo()
        old_terminal = Operation.create({
            "operation_uid": _uid(), "device_uid": "d", "client_seq": 1,
            "operation_type": TEST_ECHO_TYPE, "submitted_by_user_id": self.env.user.id,
            "submission_company_id": self.env.company.id,
            "received_at": odoo.fields.Datetime.now() - timedelta(days=100),
            "status": "accepted",
        })
        recent_terminal = Operation.create({
            "operation_uid": _uid(), "device_uid": "d", "client_seq": 2,
            "operation_type": TEST_ECHO_TYPE, "submitted_by_user_id": self.env.user.id,
            "submission_company_id": self.env.company.id, "received_at": odoo.fields.Datetime.now(),
            "status": "accepted",
        })
        old_pending = Operation.create({
            "operation_uid": _uid(), "device_uid": "d", "client_seq": 3,
            "operation_type": TEST_ECHO_TYPE, "submitted_by_user_id": self.env.user.id,
            "submission_company_id": self.env.company.id,
            "received_at": odoo.fields.Datetime.now() - timedelta(days=100),
            "status": "pending",
        })
        Operation._cron_cleanup_terminal_operations()
        self.assertFalse(old_terminal.exists())
        self.assertTrue(recent_terminal.exists())
        self.assertTrue(old_pending.exists(), "pending rows must never be auto-cleaned regardless of age")

    # -- Stage 8A: conflict snapshot policy ----------------------------------

    def test_conflict_snapshot_attached_for_business_conflicts(self):
        result = self._process(self.env, _op(TEST_REJECT_WITH_SNAPSHOT_TYPE))
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "TEST_STALE_STATE")
        self.assertEqual(result["result"], {"safe": "data"})

    def test_no_snapshot_for_access_style_rejections(self):
        # UID_CONFLICT, UNKNOWN_OPERATION, TARGET_NOT_FOUND-style rejections
        # never carry a snapshot - proven generically here for the
        # dispatcher's own unconditional-empty-result rejection paths.
        result = self._process(self.env, _op("nonexistent.operation.type"))
        self.assertEqual(result["result"], {})

    # -- Stage 8A: unexpected errors stay retryable, never a false result ---

    def test_unexpected_error_rolls_back_and_stays_retryable(self):
        partner = self.env["res.partner"].create({"name": "Offline Flaky Test Partner"})
        key = _uid()
        op = _op(TEST_FLAKY_MUTATION_TYPE, payload={"key": key, "partner_id": partner.id})

        first = self._process(self.env, op)
        self.assertEqual(first["status"], "error")
        self.assertEqual(first["reason_code"], "TEMPORARY_ERROR")
        partner.invalidate_recordset()
        # comment is an HTML field (Odoo wraps plain text as Markup('<p>...</p>')),
        # so compare on substring rather than exact equality.
        self.assertNotIn("PARTIAL", str(partner.comment or ""))

        rec = self.env["dukaku.offline.operation"].sudo().search(
            [("operation_uid", "=", op["operation_uid"])]
        )
        self.assertEqual(rec.status, "pending", "must stay non-terminal, never a false rejected result")
        self.assertEqual(rec.retry_count, 1)

        # Retry with the SAME operation_uid - resumes on the same row.
        second = self._process(self.env, op)
        self.assertEqual(second["status"], "accepted")
        self.assertFalse(second["is_duplicate"])
        partner.invalidate_recordset()
        self.assertIn("COMMITTED", str(partner.comment or ""))

        self.assertEqual(
            self.env["dukaku.offline.operation"].sudo().search_count(
                [("operation_uid", "=", op["operation_uid"])]
            ),
            1,
            "must never create a second row for the same operation_uid",
        )

    def test_unexpected_error_never_leaks_traceback_to_client(self):
        partner = self.env["res.partner"].create({"name": "Offline Flaky Test Partner 2"})
        op = _op(TEST_FLAKY_MUTATION_TYPE, payload={"key": _uid(), "partner_id": partner.id})
        result = self._process(self.env, op)
        self.assertNotIn("Traceback", str(result))
        self.assertNotIn(".py", str(result))

    # -- Stage 8A: dependent-stream ordering ---------------------------------

    def test_stream_blocking_skips_dependent_operation_same_batch(self):
        blocked = set()
        op_fail = _op(TEST_STREAM_TYPE, payload={"stream": "S", "fail": True}, client_seq=1)
        op_dependent = _op(TEST_STREAM_TYPE, payload={"stream": "S"}, client_seq=2)
        op_other = _op(TEST_STREAM_TYPE, payload={"stream": "T"}, client_seq=3)

        r1 = self._process(self.env, op_fail, blocked)
        r2 = self._process(self.env, op_dependent, blocked)
        r3 = self._process(self.env, op_other, blocked)

        self.assertEqual(r1["status"], "rejected")
        self.assertEqual(r2["status"], "rejected")
        self.assertEqual(r2["reason_code"], "DEPENDENT_STREAM_BLOCKED")
        self.assertFalse(r2["is_duplicate"])
        self.assertEqual(r3["status"], "accepted", "unrelated stream must not be blocked")

        # Stage 8A UID-determinism fix: the skipped operation IS persisted
        # as its own normal canonical row - exactly one, terminally
        # rejected - never left row-less the way an unrecorded skip would
        # allow a later submission to silently re-litigate it.
        recs = self.env["dukaku.offline.operation"].sudo().search(
            [("operation_uid", "=", op_dependent["operation_uid"])]
        )
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs.status, "rejected")
        self.assertEqual(recs.reason_code, "DEPENDENT_STREAM_BLOCKED")

    def test_stream_blocked_uid_returns_same_canonical_result_in_a_later_batch(self):
        """The exact invariant this fix closes: one operation_uid must
        never carry two different canonical outcomes. A
        DEPENDENT_STREAM_BLOCKED operation_uid resubmitted later, even in
        a batch where its stream is no longer blocked at all, must still
        return the ORIGINAL stored rejection - never re-dispatch."""
        blocked = set()
        op_fail = _op(TEST_STREAM_TYPE, payload={"stream": "V", "fail": True}, client_seq=1)
        op_dependent = _op(TEST_STREAM_TYPE, payload={"stream": "V"}, client_seq=2)
        self._process(self.env, op_fail, blocked)
        first = self._process(self.env, op_dependent, blocked)
        self.assertEqual(first["status"], "rejected")
        self.assertEqual(first["reason_code"], "DEPENDENT_STREAM_BLOCKED")

        # A fresh, later, separate batch - empty blocked_streams, and
        # stream "V" has no failing member in THIS batch at all.
        retry = self._process(self.env, op_dependent, set())
        self.assertEqual(retry["status"], "rejected")
        self.assertEqual(retry["reason_code"], "DEPENDENT_STREAM_BLOCKED")
        self.assertTrue(retry["is_duplicate"])

        self.assertEqual(
            self.env["dukaku.offline.operation"].sudo().search_count(
                [("operation_uid", "=", op_dependent["operation_uid"])]
            ),
            1,
            "must never create a second row for the same operation_uid",
        )

    def test_stream_blocking_does_not_cross_batches_for_fresh_uids(self):
        """The blocked_streams SET is batch-local bookkeeping only - it
        does not itself carry across batches. A DIFFERENT, fresh
        operation_uid submitted later for the same stream key, in a batch
        where that stream has no failing member, is evaluated on its own
        merits (not blocked just because an unrelated earlier batch once
        failed on that stream)."""
        op_fail = _op(TEST_STREAM_TYPE, payload={"stream": "U", "fail": True})
        self._process(self.env, op_fail, set())  # a fresh, separate batch (empty blocked set)

        op_later = _op(TEST_STREAM_TYPE, payload={"stream": "U"})
        result = self._process(self.env, op_later, set())  # also a fresh batch, different UID
        self.assertEqual(result["status"], "accepted", "blocked_streams bookkeeping must not persist across batches")

    def test_temporary_error_uid_still_retries_pending_after_dependency_fix(self):
        """Item 14/regression: TEMPORARY_ERROR operations must remain
        wholly unaffected by the dependent-stream persistence change -
        still 'pending', still retryable under the SAME operation_uid,
        never confused with a terminal DEPENDENT_STREAM_BLOCKED outcome."""
        partner = self.env["res.partner"].create({"name": "Offline Temp Error Regression Partner"})
        key = _uid()
        op = _op(TEST_FLAKY_MUTATION_TYPE, payload={"key": key, "partner_id": partner.id})

        first = self._process(self.env, op)
        self.assertEqual(first["status"], "error")
        self.assertEqual(first["reason_code"], "TEMPORARY_ERROR")
        rec = self.env["dukaku.offline.operation"].sudo().search(
            [("operation_uid", "=", op["operation_uid"])]
        )
        self.assertEqual(rec.status, "pending")

        second = self._process(self.env, op)  # same UID, same batch-independent retry
        self.assertEqual(second["status"], "accepted")
        self.assertFalse(second["is_duplicate"])

    # Genuine concurrent-duplicate-UID coverage lives in
    # TestDukakuOfflineOperationEndpoint.test_concurrent_duplicate_uid_via_http
    # below, not here - self.registry.cursor() inside a TransactionCase
    # does not open a genuinely independent connection (it shares the same
    # underlying test transaction via TestCursor), so two threads racing
    # on it don't exercise real Postgres-level concurrency at all; in
    # practice it reliably deadlocked instead. Real HTTP requests each get
    # a real, independent connection, which is what this needs.


@odoo.tests.tagged("post_install", "-at_install")
class TestDukakuOfflineOperationEndpoint(HttpCase):
    """A small end-to-end slice through the real network-facing route,
    proving the route is genuinely reachable, auth='user' genuinely
    refuses an unauthenticated request, and a genuinely authenticated
    request reaches a registered handler and returns the canonical
    response - the bulk of business-logic coverage lives in the direct-
    call tests above.

    This server's production dbfilter (^%d$) requires the request's Host
    header to equal the database name before request dispatch will
    resolve a database at all - without it, every request in this class
    404s at the routing layer before auth is even consulted. Rather than
    touch that production configuration (a file on disk, shared with the
    live server), dbfilter is relaxed only in THIS test process's own
    in-memory config for the lifetime of each test method, restored
    immediately after - the actual application/route code under test is
    completely unchanged; only how *this test process* resolves a
    database differs, and only for its own duration.

    A manually-forced Host header was tried as an alternative and
    discarded: it got past the dbfilter 404, but then broke session
    validation on the very next request (authenticate() succeeds, then
    the following request reports "Session expired") - a second,
    independent effect of overriding Host, not just a dbfilter one.
    Relaxing dbfilter directly avoids needing any Host override at all.
    """

    def setUp(self):
        super().setUp()
        from odoo.tools import config as odoo_config
        self._previous_dbfilter = odoo_config.get("dbfilter")
        odoo_config["dbfilter"] = ""
        self.addCleanup(lambda: odoo_config.__setitem__("dbfilter", self._previous_dbfilter))

    def test_submit_operations_requires_authenticated_session(self):
        # No self.authenticate() call - no session. auth='user' must refuse
        # the request rather than execute it as some default/public user.
        with self.assertRaises(JsonRpcException):
            self.make_jsonrpc_request(
                "/dukaku_offline/submit_operations",
                {"operations": [_op(TEST_ECHO_TYPE)]},
            )

    def test_submit_operations_end_to_end_authenticated(self):
        admin_login = self.env.ref("base.user_admin").login
        self.authenticate(admin_login, "unused")
        op = _op(TEST_ECHO_TYPE, payload={"ping": "pong"})
        result = self.make_jsonrpc_request(
            "/dukaku_offline/submit_operations",
            {"operations": [op]},
        )
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["status"], "accepted")
        self.assertEqual(result["results"][0]["result"]["echo"], {"ping": "pong"})

    def test_concurrent_duplicate_uid_via_http_executes_exactly_once(self):
        """Two genuinely concurrent HTTP requests submitting the SAME
        operation_uid - each request gets its own real, independent DB
        connection (unlike a TransactionCase's shared TestCursor), so this
        exercises real Postgres-level contention on the unique constraint,
        not just a simulated/sequential reproduction of it.

        Each thread uses its OWN plain `requests.Session` rather than
        `self.opener`/`self.make_jsonrpc_request()`: Odoo's `Opener` wraps
        a `requests.Session`, and sharing one across threads reliably
        deadlocked here (and left orphaned background threads that then
        corrupted later tests in this class) - a first attempt sharing
        `self.opener` is exactly what produced that failure. A plain,
        thread-local `requests.Session` per worker, carrying only the
        session cookie value copied out of `self.session` beforehand,
        avoids any object shared between threads entirely.
        """
        import requests as requests_lib

        admin_login = self.env.ref("base.user_admin").login
        session = self.authenticate(admin_login, "unused")
        session_cookie = session.sid
        url = self.base_url() + "/dukaku_offline/submit_operations"

        shared_uid = _uid()
        op = _op(TEST_ECHO_TYPE, operation_uid=shared_uid, payload={"race": True})
        body = {"jsonrpc": "2.0", "method": "call", "id": 0, "params": {"operations": [op]}}

        results = []
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                with requests_lib.Session() as s:
                    s.cookies.set("session_id", session_cookie)
                    barrier.wait(timeout=5)
                    resp = s.post(url, json=body, timeout=20)
                    if resp.status_code >= 400:
                        raise RuntimeError(f"{resp.status_code}: {resp.text[:500]}")
                    decoded = resp.json()
                    if "error" in decoded:
                        raise RuntimeError(decoded["error"])
                    results.append(decoded["result"]["results"][0])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        # HttpCase normally serializes requests made through self.opener:
        # each individual call briefly releases a global test-registry
        # lock (see release_test_lock()/allow_requests() in odoo/tests/
        # common.py) just for that one call's duration, and also stamps a
        # short-lived per-call cookie the server checks for - both
        # designed around one request at a time, not genuinely concurrent
        # ones. all_requests=True bypasses the per-call cookie check
        # entirely and holds the lock released for the whole `with` block,
        # so both threads' overlapping requests can actually execute
        # concurrently instead of deadlocking against it.
        with self.allow_requests(all_requests=True):
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=25)
                self.assertFalse(t.is_alive(), "worker thread did not finish in time")

        self.assertFalse(errors, f"worker threads raised: {errors}")
        self.assertEqual(len(results), 2)
        self.assertEqual([r["status"] for r in results], ["accepted", "accepted"])
        # Exactly one request actually executed the handler; the other
        # replayed the stored result - never both, never neither.
        self.assertEqual(sorted(r["is_duplicate"] for r in results), [False, True])

        count = self.env["dukaku.offline.operation"].sudo().search_count(
            [("operation_uid", "=", shared_uid)]
        )
        self.assertEqual(count, 1, "exactly one row - the DB constraint prevented a duplicate insert")
