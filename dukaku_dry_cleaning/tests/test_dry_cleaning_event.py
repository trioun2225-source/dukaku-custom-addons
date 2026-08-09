# -*- coding: utf-8 -*-
import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import mute_logger
from psycopg2 import IntegrityError


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningEvent(CommonPosTest):
    """Stage 3 tests: the dry_cleaning.event audit log and the
    dry_cleaning.ticket._transition_to() service that writes to it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dry_cleaning_product = cls.ten_dollars_no_tax
        cls.dry_cleaning_product.requires_garment_tag = True

    def _pay_order(self, product, qty, partner=None):
        order, _refund = self.create_backend_pos_order({
            "line_data": [{"product_id": product.product_variant_id.id, "qty": qty}],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
            "order_data": {"partner_id": (partner or self.partner_adgu).id},
        })
        return order

    def test_ticket_creation_creates_single_drop_off_event(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id
        events = self.env["dry_cleaning.event"].search([("ticket_id", "=", ticket.id)])

        self.assertEqual(len(events), 1)
        self.assertEqual(events.event_type, "drop_off")
        self.assertEqual(events.source, "server")
        self.assertEqual(events.company_id, ticket.company_id)

        # Re-running the idempotent get-or-create path must not add a
        # second event for the same ticket.
        self.env["dry_cleaning.ticket"]._get_or_create_for_order(order)
        events_after = self.env["dry_cleaning.event"].search([("ticket_id", "=", ticket.id)])
        self.assertEqual(len(events_after), 1)

    def test_transition_creates_matching_event_pair(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        ticket.action_start()
        self.assertEqual(ticket.state, "in_progress")
        events = self.env["dry_cleaning.event"].search([("ticket_id", "=", ticket.id)])
        self.assertEqual(len(events), 2)
        self.assertEqual(events.mapped("event_type"), ["drop_off", "in_progress"])

    def test_full_workflow_produces_ordered_events(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        ticket.action_start()
        ticket.action_mark_ready()
        ticket.action_pick_up()

        events = self.env["dry_cleaning.event"].search([("ticket_id", "=", ticket.id)])
        self.assertEqual(
            events.mapped("event_type"),
            ["drop_off", "in_progress", "ready", "picked_up"],
            "events must come back in event_at/id order matching the workflow",
        )

    def test_invalid_transition_raises_and_creates_no_event(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        with self.assertRaises(UserError):
            ticket.action_mark_ready()  # drop_off -> ready is not a valid single step

        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "drop_off", "state must not change on a rejected transition")
        events = self.env["dry_cleaning.event"].search([("ticket_id", "=", ticket.id)])
        self.assertEqual(len(events), 1, "only the initial drop_off event must exist")

    def test_event_write_raises_even_under_sudo(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        event = self.env["dry_cleaning.event"].search(
            [("ticket_id", "=", order.dry_cleaning_ticket_id.id)]
        )
        with self.assertRaises(UserError):
            event.write({"note": "tampering"})
        with self.assertRaises(UserError):
            event.sudo().write({"note": "tampering"})

    def test_event_unlink_raises_even_under_sudo(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        event = self.env["dry_cleaning.event"].search(
            [("ticket_id", "=", order.dry_cleaning_ticket_id.id)]
        )
        with self.assertRaises(UserError):
            event.unlink()
        with self.assertRaises(UserError):
            event.sudo().unlink()

    def test_garment_tag_must_belong_to_same_ticket(self):
        order_a = self._pay_order(self.dry_cleaning_product, 1)
        order_b = self._pay_order(self.dry_cleaning_product, 1)
        ticket_a = order_a.dry_cleaning_ticket_id
        tag_from_order_b = order_b.lines[0].garment_tag_ids

        # sudo() to reach the model-level constraint itself: create is no
        # longer ACL-permitted for any group (see the direct-create tests
        # below), so a plain create() here would raise AccessError first.
        with self.assertRaises(ValidationError):
            self.env["dry_cleaning.event"].sudo().create({
                "ticket_id": ticket_a.id,
                "garment_tag_id": tag_from_order_b.id,
                "event_type": "drop_off",
            })

    # -- Item 1: direct ticket.state mutation must be blocked --------------

    def test_direct_state_write_rejected(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        with self.assertRaises(UserError):
            ticket.write({"state": "in_progress"})

        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "drop_off", "a rejected direct write must not change state")
        events = self.env["dry_cleaning.event"].search([("ticket_id", "=", ticket.id)])
        self.assertEqual(len(events), 1, "a rejected direct write must not create an event")

    def test_direct_state_write_rejected_even_under_sudo(self):
        """sudo() alone must not be a way around this: only calling
        super(DryCleaningTicket, self).write() from inside _transition_to()
        bypasses the guard, and sudo() doesn't change which Python method
        gets called on an ordinary write().
        """
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        with self.assertRaises(UserError):
            ticket.sudo().write({"state": "picked_up"})

    def test_state_guard_is_narrow_not_a_blanket_write_block(self):
        """write() rejects 'state' specifically, not every field - proven
        here via an empty-dict write, which touches no field at all and so
        must succeed (record rules still apply and are covered elsewhere;
        this test is only about the state guard's own scope).

        Previously this test used {'name': 'RELABELLED'} as its "harmless"
        non-state field - that was test plumbing standing in for "some
        field write still works", never a frozen requirement that ticket
        renaming itself be legitimate. A Stage 6 identity-lock review has
        since frozen dry_cleaning.ticket.name as immutable after creation
        too (see write()'s _IMMUTABLE_AFTER_CREATE) - that guard is
        exercised in tests/test_write_surface_hardening.py, not here.
        """
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        ticket.write({})

    def test_actions_still_work_and_each_transition_creates_exactly_one_event(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        ticket.action_start()
        self.assertEqual(ticket.state, "in_progress")
        self.assertEqual(
            self.env["dry_cleaning.event"].search_count([("ticket_id", "=", ticket.id)]), 2
        )

        ticket.action_mark_ready()
        self.assertEqual(ticket.state, "ready")
        self.assertEqual(
            self.env["dry_cleaning.event"].search_count([("ticket_id", "=", ticket.id)]), 3
        )

        ticket.action_pick_up()
        self.assertEqual(ticket.state, "picked_up")
        self.assertEqual(
            self.env["dry_cleaning.event"].search_count([("ticket_id", "=", ticket.id)]), 4
        )

    # -- Item 2: no direct user-created events ------------------------------

    def test_plain_user_cannot_directly_create_event(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        plain_user = self.env["res.users"].create({
            "name": "Plain Dry Cleaning User",
            "login": "dry_cleaning_plain_user_stage3",
            "group_ids": [(6, 0, self.env.ref("dukaku_dry_cleaning.group_dry_cleaning_user").ids)],
        })
        with self.assertRaises(AccessError):
            self.env["dry_cleaning.event"].with_user(plain_user).create({
                "ticket_id": ticket.id,
                "event_type": "in_progress",
            })

    def test_manager_cannot_directly_create_event_either(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        # A manager with only the dry-cleaning manager group (not full
        # base.group_system admin) - the frozen rule is that NO group gets
        # create access on this model, manager included.
        manager_user = self.env["res.users"].create({
            "name": "Dry Cleaning Manager Direct",
            "login": "dry_cleaning_manager_direct_stage3",
            "group_ids": [(6, 0, self.env.ref("dukaku_dry_cleaning.group_dry_cleaning_manager").ids)],
        })
        with self.assertRaises(AccessError):
            self.env["dry_cleaning.event"].with_user(manager_user).create({
                "ticket_id": ticket.id,
                "event_type": "in_progress",
            })

    def test_event_actor_attribution_is_real_user_not_superuser(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        # Stage 6: action_start() now requires the Can Process capability
        # (or Manager) - a plain base-User cashier can no longer call it,
        # so this fixture needs Can Process too. The test's actual subject
        # (actor attribution on the resulting event) is unaffected.
        cashier = self.env["res.users"].create({
            "name": "Dry Cleaning Cashier",
            "login": "dry_cleaning_cashier_stage3",
            "group_ids": [(6, 0, (
                self.env.ref("dukaku_dry_cleaning.group_dry_cleaning_user")
                | self.env.ref("dukaku_dry_cleaning.group_dry_cleaning_can_process")
            ).ids)],
        })
        ticket.with_user(cashier).action_start()

        event = self.env["dry_cleaning.event"].search([
            ("ticket_id", "=", ticket.id), ("event_type", "=", "in_progress"),
        ])
        self.assertEqual(len(event), 1)
        self.assertEqual(
            event.user_id, cashier,
            "the event must be attributed to the real actor performing the transition",
        )
        self.assertNotEqual(
            event.user_id.id, odoo.SUPERUSER_ID,
            "sudo() must not cause the event to be attributed to the technical superuser",
        )

    # -- Item 3: audit retention / delete semantics -------------------------

    def test_ticket_with_events_cannot_be_deleted(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id
        event_ids_before = self.env["dry_cleaning.event"].search(
            [("ticket_id", "=", ticket.id)]
        ).ids
        self.assertTrue(event_ids_before)

        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            ticket.sudo().unlink()

        self.assertTrue(ticket.exists(), "the ticket must survive the blocked delete")
        self.assertEqual(
            self.env["dry_cleaning.event"].search([("ticket_id", "=", ticket.id)]).ids,
            event_ids_before,
            "no event may be silently lost",
        )

    def test_deleting_pos_order_with_event_bearing_ticket_is_blocked(self):
        """The order -> ticket -> event cascade chain (Stage 1's
        ticket.pos_order_id ondelete='cascade' meeting Stage 3's
        event.ticket_id ondelete='restrict').

        pos.order itself already refuses to delete a paid order (Odoo core:
        "In order to delete a sale, it must be new or cancelled"), and also
        refuses to write a paid order's state back to 'cancel' through the
        ORM - so a paid order with a dry-cleaning ticket can never reach a
        deletable state through any normal business action. To exercise the
        FK-level guarantee this test is actually about, the order is forced
        to 'cancel' via a direct SQL UPDATE, deliberately bypassing those
        write-time guards - simulating the only realistic way this chain
        could ever be reached (a migration or raw DB operation), which is
        exactly the scenario the restrict FK exists to protect against.
        """
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id
        event_ids_before = self.env["dry_cleaning.event"].search(
            [("ticket_id", "=", ticket.id)]
        ).ids
        self.assertTrue(event_ids_before)

        self.env.cr.execute(
            "UPDATE pos_order SET state = 'cancel' WHERE id = %s", (order.id,)
        )
        order.invalidate_recordset()
        self.assertEqual(order.state, "cancel")

        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            order.sudo().unlink()

        self.assertTrue(order.exists(), "the order must survive the blocked cascade")
        self.assertTrue(ticket.exists(), "the ticket must survive the blocked cascade")
        self.assertEqual(
            self.env["dry_cleaning.event"].search([("ticket_id", "=", ticket.id)]).ids,
            event_ids_before,
            "no event may be silently lost through the order->ticket cascade",
        )
