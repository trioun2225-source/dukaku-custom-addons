# -*- coding: utf-8 -*-
from unittest.mock import patch

import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest
from odoo.exceptions import UserError


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningTicketWorkflowUI(CommonPosTest):
    """Stage 4: backend ticket views load, workflow buttons call the
    existing server-side action methods (never a direct state write), and
    a stale transition is rejected cleanly with no duplicate event.
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

    def test_ticket_list_view_loads(self):
        result = self.env["dry_cleaning.ticket"].get_views([(False, "list")])
        self.assertIn("list", result["views"])

    def test_ticket_form_view_loads(self):
        result = self.env["dry_cleaning.ticket"].get_views([(False, "form")])
        self.assertIn("form", result["views"])

    def test_ticket_search_view_loads(self):
        result = self.env["dry_cleaning.ticket"].get_views([(False, "search")])
        self.assertIn("search", result["views"])

    def test_valid_workflow_action_succeeds(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id
        # This is exactly what the form's "Start Processing" button calls.
        ticket.action_start()
        self.assertEqual(ticket.state, "in_progress")

    def test_ui_path_invokes_server_action_not_direct_write(self):
        """The workflow buttons in the view are wired to action_start /
        action_mark_ready / action_pick_up (name= on each <button>), never
        to a direct field write - confirm the direct path stays blocked."""
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id
        with self.assertRaises(UserError):
            ticket.write({"state": "in_progress"})

    def test_stale_transition_produces_no_duplicate_event(self):
        """Staff A and Staff B both looking at a 'ready' ticket; B confirms
        pickup first, then A's stale click must be rejected with no
        duplicate 'picked_up' event."""
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id
        ticket.action_start()
        ticket.action_mark_ready()

        # Staff B: succeeds.
        ticket.action_pick_up()
        events_after_first_pickup = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id), ("event_type", "=", "picked_up")]
        )
        self.assertEqual(events_after_first_pickup, 1)

        # Staff A: stale click on the same (already picked-up) ticket.
        with self.assertRaises(UserError):
            ticket.action_pick_up()

        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "picked_up", "state must not have changed again")
        events_after_stale_click = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id), ("event_type", "=", "picked_up")]
        )
        self.assertEqual(
            events_after_stale_click, 1,
            "the stale transition must not have created a second picked_up event",
        )

    # -- Freeze hardening: *_ui wrappers used by the form's buttons ---------

    def test_ui_action_success_transitions_and_returns_close_action(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        result = ticket.action_start_ui()

        self.assertEqual(ticket.state, "in_progress")
        self.assertEqual(result, {"type": "ir.actions.act_window_close"})

    def test_ui_stale_transition_does_not_raise(self):
        """The *_ui wrapper must never let the underlying UserError escape -
        the whole point is a non-raising result the standard button/action
        machinery reloads on, instead of a generic error dialog."""
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id
        ticket.action_start()
        ticket.action_mark_ready()
        ticket.action_pick_up()  # "Staff B": already picked up

        # "Staff A": stale click via the UI-safe entry point - must not raise.
        result = ticket.action_pick_up_ui()

        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["tag"], "display_notification")

    def test_ui_stale_transition_message_embeds_actual_current_state(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id
        ticket.action_start()
        ticket.action_mark_ready()
        ticket.action_pick_up()  # "Staff B"

        result = ticket.action_pick_up_ui()  # "Staff A", stale

        message = result["params"]["message"]
        self.assertIn("Picked Up", message, "must contain the actual resolved state label")
        self.assertIn("already updated", message)
        self.assertNotIn(
            "%(state)s", message,
            "the %(state)s placeholder must be interpolated, never shown literally",
        )

    def test_ui_stale_transition_chains_reload_via_next_action(self):
        """This is the mechanism the standard type="object" button/action
        machinery uses to reload the record after a successful call - the
        *_ui wrapper must chain into it via 'next' rather than raising, or
        the view is left showing stale state/buttons (see receipt_screen.js
        comment / view_button_hook.js reload wiring for the same pattern)."""
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id
        ticket.action_start()
        ticket.action_mark_ready()
        ticket.action_pick_up()

        result = ticket.action_pick_up_ui()

        self.assertEqual(result["next"], {"type": "ir.actions.act_window_close"})

    def test_ui_stale_transition_creates_no_duplicate_event(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id
        ticket.action_start()
        ticket.action_mark_ready()
        ticket.action_pick_up()
        events_before = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id)]
        )

        ticket.action_pick_up_ui()  # stale, via the UI-safe entry point

        events_after = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id)]
        )
        self.assertEqual(events_before, events_after)
        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "picked_up", "state must not have changed again")

    def test_ui_wrapper_does_not_swallow_unrelated_user_error(self):
        """_ui_wrap_transition must only intercept InvalidTicketTransitionError
        (the one _check_transition raises) - any other UserError from the
        same call chain must propagate normally, not be misrepresented as a
        stale-transition notification. Simulated here since the current
        action_start/_transition_to call chain has no other real-world
        source of a plain UserError to exercise this against."""
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id

        with patch.object(
            type(ticket), "action_start",
            side_effect=UserError("Some unrelated business error"),
        ):
            with self.assertRaises(UserError) as cm:
                ticket.action_start_ui()

        # Raised, not swallowed/converted: the caller sees the real error,
        # not a display_notification dict masquerading as "already updated".
        self.assertEqual(str(cm.exception.args[0]), "Some unrelated business error")
