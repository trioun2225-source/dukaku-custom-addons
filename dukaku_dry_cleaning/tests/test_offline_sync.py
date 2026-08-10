# -*- coding: utf-8 -*-
"""Stage 8: dry-cleaning registrations against dukaku_offline's generic
synchronization layer.

Covers the backend-testable half of the Stage 7/8 offline architecture -
authorization/validity re-checked at sync time, operation vs event
separation, online-only operations having no handler at all, the
unsynced-ticket dependency, batch ordering/independence, and timestamp
authority. The client-side durable queue, IndexedDB integration, and UI
are explicitly out of scope for this backend suite (see the Stage 8
completion report for why, and what remains frontend-only work).
"""
import uuid
from datetime import timedelta

import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest
from odoo.exceptions import UserError

from odoo.addons.dukaku_offline.controllers.main import _process_one_operation


def _uid():
    return str(uuid.uuid4())


def _op(operation_type, target=None, device_uid="device-1", client_seq=1,
        payload=None, occurred_at_client=None):
    p = dict(payload or {})
    if target is not None:
        p.setdefault("ticket_id", target)
    return {
        "operation_uid": _uid(),
        "device_uid": device_uid,
        "client_seq": client_seq,
        "operation_type": operation_type,
        "payload": p,
        "occurred_at_client": occurred_at_client,
    }


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningOfflineSync(CommonPosTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dry_cleaning_product = cls.ten_dollars_no_tax
        cls.dry_cleaning_product.requires_garment_tag = True

        base_user_group = cls.env.ref("base.group_user")
        group_user = cls.env.ref("dukaku_dry_cleaning.group_dry_cleaning_user")
        group_manager = cls.env.ref("dukaku_dry_cleaning.group_dry_cleaning_manager")
        group_can_process = cls.env.ref("dukaku_dry_cleaning.group_dry_cleaning_can_process")
        group_can_pickup = cls.env.ref("dukaku_dry_cleaning.group_dry_cleaning_can_pickup")

        def _make_user(login, groups):
            return cls.env["res.users"].create({
                "name": login, "login": login,
                "group_ids": [(6, 0, (groups | base_user_group).ids)],
            })

        cls.cashier = _make_user("offline_cashier", group_user)
        cls.processor = _make_user("offline_processor", group_user | group_can_process)
        cls.pickup_staff = _make_user("offline_pickup", group_user | group_can_pickup)
        cls.manager = _make_user("offline_manager", group_manager)

    def _pay_order(self, product=None, qty=1, partner=None):
        order, _refund = self.create_backend_pos_order({
            "line_data": [{
                "product_id": (product or self.dry_cleaning_product).product_variant_id.id,
                "qty": qty,
            }],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
            "order_data": {"partner_id": (partner or self.partner_adgu).id},
        })
        return order

    def _ticket_and_tag(self, qty=1):
        order = self._pay_order(qty=qty)
        return order.dry_cleaning_ticket_id, order.lines[0].garment_tag_ids

    def _process(self, user, op, blocked_streams=None):
        return _process_one_operation(
            self.env(user=user), op, blocked_streams if blocked_streams is not None else set()
        )

    # -- 17-18: Start Processing ----------------------------------------

    def test_17_start_processing_accepted_with_capability(self):
        ticket, _tag = self._ticket_and_tag()
        result = self._process(
            self.processor, _op("dry_cleaning.start_processing", target=ticket.id)
        )
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["result"]["state"], "in_progress")
        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "in_progress")

    def test_18_start_processing_rejected_without_capability(self):
        ticket, _tag = self._ticket_and_tag()
        result = self._process(
            self.cashier, _op("dry_cleaning.start_processing", target=ticket.id)
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "NOT_AUTHORIZED")
        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "drop_off")

    # -- 19-20: Mark Ready -------------------------------------------------

    def test_19_mark_ready_accepted_appropriately(self):
        ticket, _tag = self._ticket_and_tag()
        ticket.action_start()
        result = self._process(
            self.processor, _op("dry_cleaning.mark_ready", target=ticket.id)
        )
        self.assertEqual(result["status"], "accepted")
        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "ready")

    def test_20_mark_ready_stale_conflict_rejected(self):
        """Terminal A cached in_progress and queues Mark Ready offline while,
        in the meantime, the ticket has already been fully picked up by
        another terminal - the Stage 7 conflict example."""
        ticket, _tag = self._ticket_and_tag()
        ticket.action_start()
        ticket.action_mark_ready()
        ticket.action_pick_up()

        result = self._process(
            self.processor, _op("dry_cleaning.mark_ready", target=ticket.id)
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "STALE_STATE")
        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "picked_up", "authoritative state must be unchanged")

        # Stage 8A: the target was legitimately resolved/visible, so the
        # client gets an authoritative snapshot to reconcile its cache.
        snapshot = result["result"]
        self.assertEqual(snapshot["ticket_id"], ticket.id)
        self.assertEqual(snapshot["state"], "picked_up")
        self.assertEqual(snapshot["ticket_name"], ticket.name)

    def test_20b_no_snapshot_for_not_authorized_rejection(self):
        """Access-denied rejections never carry a target snapshot, even
        though the record was technically resolved - Stage 8A draws this
        line at the handler level, not just for genuinely-unresolvable
        targets."""
        ticket, _tag = self._ticket_and_tag()
        result = self._process(
            self.cashier, _op("dry_cleaning.start_processing", target=ticket.id)
        )
        self.assertEqual(result["reason_code"], "NOT_AUTHORIZED")
        self.assertEqual(result["result"], {})

    def test_20c_no_snapshot_for_target_not_found(self):
        result = self._process(
            self.processor, _op("dry_cleaning.start_processing", target=99999999)
        )
        self.assertEqual(result["reason_code"], "TARGET_NOT_FOUND")
        self.assertEqual(result["result"], {})

    # -- 21-23: operation vs event -----------------------------------------

    def test_21_rejected_transition_produces_no_event(self):
        ticket, _tag = self._ticket_and_tag()
        events_before = self.env["dry_cleaning.event"].search_count([("ticket_id", "=", ticket.id)])
        self._process(self.cashier, _op("dry_cleaning.start_processing", target=ticket.id))
        events_after = self.env["dry_cleaning.event"].search_count([("ticket_id", "=", ticket.id)])
        self.assertEqual(events_before, events_after)

    def test_22_accepted_transition_produces_exactly_one_event(self):
        ticket, _tag = self._ticket_and_tag()
        events_before = self.env["dry_cleaning.event"].search_count([("ticket_id", "=", ticket.id)])
        self._process(self.processor, _op("dry_cleaning.start_processing", target=ticket.id))
        events_after = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id), ("event_type", "=", "in_progress")]
        )
        self.assertEqual(events_after, 1)
        self.assertEqual(
            self.env["dry_cleaning.event"].search_count([("ticket_id", "=", ticket.id)]),
            events_before + 1,
        )

    def test_23_retry_accepted_transition_produces_no_duplicate_event(self):
        ticket, _tag = self._ticket_and_tag()
        op = _op("dry_cleaning.start_processing", target=ticket.id)
        self._process(self.processor, op)
        self._process(self.processor, op)  # same operation_uid, retried
        count = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id), ("event_type", "=", "in_progress")]
        )
        self.assertEqual(count, 1)

    # -- 24-26: intake note ---------------------------------------------

    def test_24_intake_note_update_accepted_while_allowed(self):
        _ticket, tag = self._ticket_and_tag()
        result = self._process(
            self.cashier,
            _op("dry_cleaning.update_intake_note", payload={"garment_tag_id": tag.id, "note": "handle with care"}),
        )
        self.assertEqual(result["status"], "accepted")
        tag.invalidate_recordset()
        self.assertEqual(tag.intake_note, "handle with care")

    def test_25_intake_note_update_rejected_once_ready(self):
        ticket, tag = self._ticket_and_tag()
        ticket.action_start()
        ticket.action_mark_ready()
        result = self._process(
            self.manager,
            _op("dry_cleaning.update_intake_note", payload={"garment_tag_id": tag.id, "note": "too late"}),
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "LIFECYCLE_LOCKED")
        tag.invalidate_recordset()
        self.assertFalse(tag.intake_note)

    def test_26_intake_note_authorization_enforced_at_sync_time(self):
        """Queued while in_progress under a user who could edit it then;
        by sync time the ticket has moved on - authorization/lifecycle are
        both re-evaluated live, never trusted from queue time."""
        _ticket, tag = self._ticket_and_tag()
        result = self._process(
            self.pickup_staff,
            _op("dry_cleaning.update_intake_note", payload={"garment_tag_id": tag.id, "note": "x"}),
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "NOT_AUTHORIZED")

    # -- 27-29: online-only operations have no handler ----------------------

    def test_27_confirm_pickup_has_no_offline_handler(self):
        ticket, _tag = self._ticket_and_tag()
        ticket.action_start()
        ticket.action_mark_ready()
        result = self._process(
            self.manager, _op("dry_cleaning.confirm_pickup", target=ticket.id)
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "UNKNOWN_OPERATION")
        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "ready", "pickup must not have been executed")

    def test_28_initial_print_has_no_offline_handler(self):
        _ticket, tag = self._ticket_and_tag()
        result = self._process(
            self.cashier, _op("dry_cleaning.print_garment_tags", payload={"garment_tag_id": tag.id})
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "UNKNOWN_OPERATION")
        tag.invalidate_recordset()
        self.assertFalse(tag.printed)

    def test_29_reprint_has_no_offline_handler(self):
        _ticket, tag = self._ticket_and_tag()
        tag.action_print_garment_tags()
        result = self._process(
            self.manager, _op("dry_cleaning.reprint_garment_tags", payload={"garment_tag_id": tag.id})
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "UNKNOWN_OPERATION")

    # -- 30-32: unsynced POS order / no offline tag or barcode creation -----

    def test_30_unsynced_ticket_dependency_cannot_be_targeted(self):
        """A ticket_id with no corresponding server record (the client's
        offline-cached POS order never having synced) resolves cleanly to
        TARGET_NOT_FOUND - it is never possible to queue a dry-cleaning
        operation against a ticket that doesn't exist server-side yet."""
        never_existed_id = 99999999
        self.assertFalse(self.env["dry_cleaning.ticket"].browse(never_existed_id).exists())
        result = self._process(
            self.processor, _op("dry_cleaning.start_processing", target=never_existed_id)
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "TARGET_NOT_FOUND")

    def test_31_32_no_offline_tag_or_barcode_creation_handler(self):
        result = self._process(
            self.manager, _op("dry_cleaning.create_garment_tag", payload={"pos_order_line_id": 1})
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason_code"], "UNKNOWN_OPERATION")

    # -- 33-36: ordering / batch independence / cross-device ----------------

    def test_33_same_device_queue_honors_client_sequence(self):
        """Submitted out of array order but with client_seq 1 then 2 - the
        server must process seq 1 (start) before seq 2 (mark ready), or the
        second would stale-reject."""
        ticket, _tag = self._ticket_and_tag()
        op_start = _op("dry_cleaning.start_processing", target=ticket.id, client_seq=1)
        op_ready = _op("dry_cleaning.mark_ready", target=ticket.id, client_seq=2)
        ordered = sorted([op_ready, op_start], key=lambda o: o["client_seq"])
        blocked_streams = set()
        results = [self._process(self.processor, o, blocked_streams) for o in ordered]
        self.assertEqual(results[0]["status"], "accepted")
        self.assertEqual(results[1]["status"], "accepted")
        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "ready")

    def test_34_failure_on_ticket_blocks_dependent_stream_same_batch(self):
        """Stage 8A's exact scenario, updated for the UID-determinism fix:
        Start Processing on ticket A is rejected; a queued Update Intake
        Note against a tag on the SAME ticket is skipped (never even
        dispatched) because dukaku_offline's generic dispatcher tracks
        ticket A's stream as blocked for the rest of this one batch, but
        IS still persisted with its own canonical terminal
        DEPENDENT_STREAM_BLOCKED row (items 1-8); a valid operation on
        unrelated ticket B still processes normally (item 13)."""
        ticket_a, tag_a = self._ticket_and_tag()
        ticket_b, _tag_b = self._ticket_and_tag()
        blocked_streams = set()

        r1 = self._process(
            self.cashier,  # lacks Can Process -> NOT_AUTHORIZED, a terminal rejection
            _op("dry_cleaning.start_processing", target=ticket_a.id, client_seq=1),
            blocked_streams,
        )
        self.assertEqual(r1["status"], "rejected")
        self.assertEqual(r1["reason_code"], "NOT_AUTHORIZED")

        skip_op = _op(
            "dry_cleaning.update_intake_note",
            payload={"garment_tag_id": tag_a.id, "note": "should be skipped"}, client_seq=2,
        )
        events_before = self.env["dry_cleaning.event"].search_count([("ticket_id", "=", ticket_a.id)])

        r2 = self._process(self.cashier, skip_op, blocked_streams)
        self.assertEqual(r2["status"], "rejected")
        self.assertEqual(r2["reason_code"], "DEPENDENT_STREAM_BLOCKED")
        tag_a.invalidate_recordset()
        self.assertFalse(tag_a.intake_note, "the skipped operation must never have been dispatched")
        self.assertEqual(
            self.env["dry_cleaning.event"].search_count([("ticket_id", "=", ticket_a.id)]),
            events_before,
            "a dependent-stream-blocked skip must create no dry-cleaning event",
        )

        # Persisted as exactly one canonical operation row (items 5-6).
        recs = self.env["dukaku.offline.operation"].sudo().search(
            [("operation_uid", "=", skip_op["operation_uid"])]
        )
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs.status, "rejected")
        self.assertEqual(recs.reason_code, "DEPENDENT_STREAM_BLOCKED")

        r3 = self._process(
            self.processor,
            _op("dry_cleaning.start_processing", target=ticket_b.id, client_seq=3),
            blocked_streams,
        )
        self.assertEqual(r3["status"], "accepted", "unrelated ticket B's stream must not be blocked")
        ticket_b.invalidate_recordset()
        self.assertEqual(ticket_b.state, "in_progress")

    def test_34b_stream_blocked_operation_uid_stays_rejected_forever(self):
        """Stage 8A UID-determinism fix: a DEPENDENT_STREAM_BLOCKED
        operation_uid must never resolve to a second, different canonical
        outcome - not even on a later, separate submission after the
        underlying conflict has been resolved (items 9-11)."""
        ticket_a, tag_a = self._ticket_and_tag()
        blocked_streams = set()
        self._process(
            self.cashier, _op("dry_cleaning.start_processing", target=ticket_a.id, client_seq=1),
            blocked_streams,
        )
        skip_op = _op(
            "dry_cleaning.update_intake_note",
            payload={"garment_tag_id": tag_a.id, "note": "first attempt"}, client_seq=2,
        )
        first = self._process(self.cashier, skip_op, blocked_streams)
        self.assertEqual(first["status"], "rejected")
        self.assertEqual(first["reason_code"], "DEPENDENT_STREAM_BLOCKED")

        # Resubmitted later, in a fresh batch, by its ORIGINAL submitter
        # (device retry) - the SAME operation_uid must still return the
        # stored rejected canonical result, never re-dispatch the handler,
        # even though the earlier NOT_AUTHORIZED conflict on the ticket is
        # no longer even present.
        retry = self._process(self.cashier, skip_op, set())
        self.assertEqual(retry["status"], "rejected")
        self.assertEqual(retry["reason_code"], "DEPENDENT_STREAM_BLOCKED")
        self.assertTrue(retry["is_duplicate"])
        tag_a.invalidate_recordset()
        self.assertFalse(tag_a.intake_note, "a same-UID retry must never dispatch the handler")

        # A DIFFERENT user retrying the exact same operation_uid is a
        # distinct, pre-existing security check (ownership), not this
        # fix's concern - it must still get UID_CONFLICT, never the
        # original submitter's stored result.
        other_user_retry = self._process(self.processor, skip_op, set())
        self.assertEqual(other_user_retry["reason_code"], "UID_CONFLICT")

        self.assertEqual(
            self.env["dukaku.offline.operation"].sudo().search_count(
                [("operation_uid", "=", skip_op["operation_uid"])]
            ),
            1,
            "must never create a second row for the same operation_uid",
        )

    def test_34c_new_uid_for_the_same_business_intent_is_a_fresh_attempt(self):
        """Item 12: once the underlying conflict is resolved, a genuinely
        NEW operation_uid for the same business intent is evaluated fresh
        against current state and may succeed."""
        ticket_a, tag_a = self._ticket_and_tag()
        blocked_streams = set()
        self._process(
            self.cashier, _op("dry_cleaning.start_processing", target=ticket_a.id, client_seq=1),
            blocked_streams,
        )
        skip_op = _op(
            "dry_cleaning.update_intake_note",
            payload={"garment_tag_id": tag_a.id, "note": "should be skipped"}, client_seq=2,
        )
        self._process(self.cashier, skip_op, blocked_streams)

        # A deliberate new attempt: new operation_uid, done by an
        # authorized user, in its own fresh batch.
        new_attempt = _op(
            "dry_cleaning.update_intake_note",
            payload={"garment_tag_id": tag_a.id, "note": "retried with a new uid"},
        )
        result = self._process(self.cashier, new_attempt, set())
        self.assertEqual(result["status"], "accepted")
        tag_a.invalidate_recordset()
        self.assertEqual(tag_a.intake_note, "retried with a new uid")

    def test_35_failure_on_one_ticket_does_not_block_unrelated_ticket(self):
        ticket_a, _tag_a = self._ticket_and_tag()
        ticket_b, _tag_b = self._ticket_and_tag()
        result_a = self._process(self.cashier, _op("dry_cleaning.start_processing", target=ticket_a.id))
        result_b = self._process(self.processor, _op("dry_cleaning.start_processing", target=ticket_b.id))
        self.assertEqual(result_a["status"], "rejected")
        self.assertEqual(result_b["status"], "accepted")
        ticket_b.invalidate_recordset()
        self.assertEqual(ticket_b.state, "in_progress")

    def test_36_cross_device_conflict_resolved_by_server_state(self):
        """Device A (seq 20) and Device B (seq 3) - no inherent global
        ordering relationship; whichever operation is actually valid
        against live server state at the moment it's processed succeeds."""
        ticket, _tag = self._ticket_and_tag()
        device_a_op = _op("dry_cleaning.start_processing", target=ticket.id, device_uid="A", client_seq=20)
        result_a = self._process(self.processor, device_a_op)
        self.assertEqual(result_a["status"], "accepted")

        device_b_op = _op("dry_cleaning.start_processing", target=ticket.id, device_uid="B", client_seq=3)
        result_b = self._process(self.processor, device_b_op)
        self.assertEqual(result_b["status"], "rejected")
        self.assertEqual(result_b["reason_code"], "STALE_STATE")

    # -- 37-38: timestamps ---------------------------------------------

    def test_37_38_client_occurrence_time_never_sets_event_time(self):
        ticket, _tag = self._ticket_and_tag()
        far_past = "2000-01-01 00:00:00"
        self._process(
            self.processor,
            _op("dry_cleaning.start_processing", target=ticket.id, occurred_at_client=far_past),
        )
        event = self.env["dry_cleaning.event"].search([
            ("ticket_id", "=", ticket.id), ("event_type", "=", "in_progress"),
        ])
        self.assertEqual(len(event), 1)
        self.assertNotEqual(str(event.event_at)[:4], "2000", "event_at must not be the client-supplied time")
        # Server time, i.e. "now" - loosely bounded, not an exact match.
        self.assertGreater(str(event.event_at), "2020-01-01 00:00:00")

    # -- cache/result minimization (proxy for the frontend cache schema) ----

    def test_result_snapshot_excludes_sensitive_customer_fields(self):
        ticket, _tag = self._ticket_and_tag()
        result = self._process(self.processor, _op("dry_cleaning.start_processing", target=ticket.id))
        snapshot = result["result"]
        self.assertEqual(set(snapshot.keys()), {"ticket_id", "ticket_name", "state", "company_id"})
        for forbidden in ("phone", "email", "street", "payment", "amount"):
            self.assertNotIn(forbidden, str(snapshot).lower())

    # -- retention: dry_cleaning.event survives operation cleanup -----------

    def test_48_dry_cleaning_event_survives_operation_cleanup(self):
        ticket, _tag = self._ticket_and_tag()
        self._process(self.processor, _op("dry_cleaning.start_processing", target=ticket.id))
        event = self.env["dry_cleaning.event"].search([
            ("ticket_id", "=", ticket.id), ("event_type", "=", "in_progress"),
        ])
        self.assertTrue(event)

        Operation = self.env["dukaku.offline.operation"].sudo()
        op_rec = Operation.search([], order="id desc", limit=1)
        op_rec.write({"received_at": odoo.fields.Datetime.now() - timedelta(days=200)})
        Operation._cron_cleanup_terminal_operations(retention_days=1)
        self.assertTrue(event.exists(), "dry_cleaning.event must never be touched by offline-operation cleanup")

    # -- 52: integration works with both modules installed -------------------

    def test_52_end_to_end_integration_both_modules_installed(self):
        ticket, tag = self._ticket_and_tag()
        r1 = self._process(self.processor, _op("dry_cleaning.start_processing", target=ticket.id))
        r2 = self._process(self.processor, _op("dry_cleaning.mark_ready", target=ticket.id))
        r3 = self._process(self.pickup_staff, _op("dry_cleaning.mark_ready", target=ticket.id))
        self.assertEqual(r1["status"], "accepted")
        self.assertEqual(r2["status"], "accepted")
        self.assertEqual(r3["status"], "rejected")
        self.assertEqual(r3["reason_code"], "NOT_AUTHORIZED")
        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "ready")
