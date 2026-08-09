# -*- coding: utf-8 -*-
"""Stage 6: implementation of the frozen Stage 5 security architecture.

Covers the hybrid group model (User/Manager base groups + Can Process/
Can Pickup/Can Reprint capability groups), the centralized
_ensure_authorized() helper, the tightened ticket/tag create+unlink ACLs,
the intake_note guarded write, capability-gated printing, and multi-company
isolation of all of the above - against real non-superuser test users, both
via ORM method calls (RPC-equivalent) and direct write()/create()/unlink()
attempts, never relying on sudo() fixtures for the isolation checks.
"""
import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest
from odoo.exceptions import AccessError, UserError


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningStage6Security(CommonPosTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dry_cleaning_product = cls.ten_dollars_no_tax
        cls.dry_cleaning_product.requires_garment_tag = True
        cls.env.company.external_report_layout_id = cls.env.ref("web.external_layout_standard")

        Group = cls.env.ref
        cls.group_user = Group("dukaku_dry_cleaning.group_dry_cleaning_user")
        cls.group_manager = Group("dukaku_dry_cleaning.group_dry_cleaning_manager")
        cls.group_can_process = Group("dukaku_dry_cleaning.group_dry_cleaning_can_process")
        cls.group_can_pickup = Group("dukaku_dry_cleaning.group_dry_cleaning_can_pickup")
        cls.group_can_reprint = Group("dukaku_dry_cleaning.group_dry_cleaning_can_reprint")

        base_user_group = cls.env.ref("base.group_user")

        def _make_user(login, groups):
            # base.group_user (Internal User) is included because every
            # real dry-cleaning staff account is an Odoo employee login,
            # not a portal/public one - without it, unrelated core ACLs
            # (e.g. reading ir.actions.report to print a label) would
            # reject these test users for reasons that have nothing to do
            # with the dry-cleaning authorization being tested here.
            return cls.env["res.users"].create({
                "name": login,
                "login": login,
                "group_ids": [(6, 0, (groups | base_user_group).ids)],
            })

        # Base role archetypes from the frozen hybrid model.
        cls.cashier = _make_user("stage6_cashier", cls.group_user)
        cls.processor = _make_user("stage6_processor", cls.group_user | cls.group_can_process)
        cls.pickup_staff = _make_user("stage6_pickup", cls.group_user | cls.group_can_pickup)
        cls.reprint_staff = _make_user("stage6_reprint", cls.group_user | cls.group_can_reprint)
        cls.small_shop_staff = _make_user(
            "stage6_small_shop", cls.group_user | cls.group_can_process | cls.group_can_pickup
        )
        # Manager group only - not base.group_system - so this exercises
        # exactly what the hybrid model grants, nothing more.
        cls.manager = _make_user("stage6_manager", cls.group_manager)

        # Second company, for cross-company isolation checks.
        cls.company_2 = cls.setup_other_company()["company"]
        cls.env.user.company_ids = [(6, 0, cls.env.company.ids)]
        cls.other_company_manager = cls.env["res.users"].sudo().create({
            "name": "Other Company Dry Cleaning Manager",
            "login": "stage6_other_company_manager",
            "company_id": cls.company_2.id,
            "company_ids": [(6, 0, cls.company_2.ids)],
            "group_ids": [(6, 0, (
                cls.group_manager | base_user_group
                | cls.env.ref("point_of_sale.group_pos_manager")
            ).ids)],
        })

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

    # ==================================================================
    # 1. Group hierarchy
    # ==================================================================

    def test_01_base_user_has_read_but_no_workflow_capability(self):
        ticket, _tag = self._ticket_and_tag()
        # Read works (base ACL)...
        self.assertTrue(ticket.with_user(self.cashier).read(["name"]))
        # ...but no workflow capability is granted by the base group alone.
        with self.assertRaises(AccessError):
            ticket.with_user(self.cashier).action_start()

    def test_02_can_process_grants_start_and_mark_ready(self):
        ticket, _tag = self._ticket_and_tag()
        ticket.with_user(self.processor).action_start()
        self.assertEqual(ticket.state, "in_progress")
        ticket.with_user(self.processor).action_mark_ready()
        self.assertEqual(ticket.state, "ready")

    def test_03_can_pickup_grants_confirm_pickup(self):
        ticket, _tag = self._ticket_and_tag()
        ticket.action_start()
        ticket.action_mark_ready()
        ticket.with_user(self.pickup_staff).action_pick_up()
        self.assertEqual(ticket.state, "picked_up")

    def test_04_can_reprint_grants_reprint(self):
        _ticket, tag = self._ticket_and_tag()
        tag.action_print_garment_tags()  # initial print, as the default user
        tag.with_user(self.reprint_staff).action_print_garment_tags()  # reprint
        self.assertTrue(tag.printed)

    def test_05_manager_effectively_receives_all_three_capabilities(self):
        ticket, tag = self._ticket_and_tag()
        ticket.with_user(self.manager).action_start()
        ticket.with_user(self.manager).action_mark_ready()
        ticket.with_user(self.manager).action_pick_up()
        self.assertEqual(ticket.state, "picked_up")
        tag.with_user(self.manager).action_print_garment_tags()
        tag.with_user(self.manager).action_print_garment_tags()  # reprint
        self.assertTrue(tag.printed)

    def test_06_no_capability_implies_unrelated_admin_groups(self):
        unrelated = (
            self.env.ref("base.group_system")
            | self.env.ref("point_of_sale.group_pos_manager")
            | self.env.ref("stock.group_stock_manager")
            | self.env.ref("account.group_account_manager")
        )
        for user in (self.cashier, self.processor, self.pickup_staff,
                     self.reprint_staff, self.manager):
            self.assertFalse(
                set(user.group_ids.ids) & set(unrelated.ids),
                f"{user.login} must not have gained an unrelated admin group",
            )

    # ==================================================================
    # 7-17. Workflow authorization
    # ==================================================================

    def test_07_08_base_user_blocked_processor_allowed_start(self):
        ticket, _tag = self._ticket_and_tag()
        with self.assertRaises(AccessError):
            ticket.with_user(self.cashier).action_start()
        ticket.with_user(self.processor).action_start()
        self.assertEqual(ticket.state, "in_progress")

    def test_09_10_base_user_blocked_processor_allowed_mark_ready(self):
        ticket, _tag = self._ticket_and_tag()
        ticket.action_start()
        with self.assertRaises(AccessError):
            ticket.with_user(self.cashier).action_mark_ready()
        ticket.with_user(self.processor).action_mark_ready()
        self.assertEqual(ticket.state, "ready")

    def test_11_12_base_user_blocked_pickup_allowed_confirm_pickup(self):
        ticket, _tag = self._ticket_and_tag()
        ticket.action_start()
        ticket.action_mark_ready()
        with self.assertRaises(AccessError):
            ticket.with_user(self.cashier).action_pick_up()
        ticket.with_user(self.pickup_staff).action_pick_up()
        self.assertEqual(ticket.state, "picked_up")

    def test_13_manager_can_perform_all_valid_transitions(self):
        ticket, _tag = self._ticket_and_tag()
        ticket.with_user(self.manager).action_start()
        ticket.with_user(self.manager).action_mark_ready()
        ticket.with_user(self.manager).action_pick_up()
        self.assertEqual(ticket.state, "picked_up")

    def test_14_manager_still_cannot_skip_states(self):
        ticket, _tag = self._ticket_and_tag()
        with self.assertRaises(UserError):
            ticket.with_user(self.manager).action_mark_ready()  # drop_off -> ready
        ticket.invalidate_recordset()
        self.assertEqual(ticket.state, "drop_off")

    def test_15_unauthorized_direct_method_invocation_rejected(self):
        """Same check as the UI path, invoked exactly as an RPC call would -
        no view/button involved at all."""
        ticket, _tag = self._ticket_and_tag()
        with self.assertRaises(AccessError):
            self.env["dry_cleaning.ticket"].with_user(self.cashier).browse(
                ticket.id
            ).action_mark_ready()

    def test_16_ui_wrapper_cannot_bypass_missing_capability(self):
        """_ui_wrap_transition only catches InvalidTicketTransitionError -
        AccessError from _ensure_authorized must propagate unchanged."""
        ticket, _tag = self._ticket_and_tag()
        with self.assertRaises(AccessError):
            ticket.with_user(self.cashier).action_start_ui()

    def test_17_barcode_wizard_cannot_bypass_missing_capability(self):
        _ticket, tag = self._ticket_and_tag()
        wizard = self.env["dry_cleaning.barcode_lookup"].with_user(self.cashier).create({})
        wizard.barcode = tag.barcode
        wizard._onchange_barcode()
        with self.assertRaises(AccessError):
            wizard.action_ticket_start()

    # ==================================================================
    # 18-22. Ticket ACL
    # ==================================================================

    def test_18_19_base_user_and_manager_cannot_directly_create_ticket(self):
        # A second, ticketless order (no qualifying line) - just need a
        # legitimate pos_order_id to attempt the direct create() against.
        order, _refund = self.create_backend_pos_order({
            "line_data": [{"product_id": self.twenty_dollars_no_tax.product_variant_id.id, "qty": 1}],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
        })
        for user in (self.cashier, self.manager):
            with self.assertRaises(AccessError):
                self.env["dry_cleaning.ticket"].with_user(user).create({
                    "pos_order_id": order.id,
                })

    def test_20_21_base_user_and_manager_cannot_unlink_ticket(self):
        ticket, _tag = self._ticket_and_tag()
        for user in (self.cashier, self.manager):
            with self.assertRaises(AccessError):
                ticket.with_user(user).unlink()
        self.assertTrue(ticket.exists())

    def test_22_legitimate_pos_flow_still_creates_ticket(self):
        order = self._pay_order()
        self.assertTrue(order.dry_cleaning_ticket_id)

    # ==================================================================
    # 23-27. Garment tag ACL
    # ==================================================================

    def test_23_24_base_user_and_manager_cannot_directly_create_tag(self):
        order = self._pay_order()
        line = order.lines[0]
        for user in (self.cashier, self.manager):
            with self.assertRaises(AccessError):
                self.env["dry_cleaning.garment_tag"].with_user(user).create({
                    "pos_order_line_id": line.id,
                })

    def test_25_26_base_user_and_manager_cannot_unlink_tag(self):
        _ticket, tag = self._ticket_and_tag()
        for user in (self.cashier, self.manager):
            with self.assertRaises(AccessError):
                tag.with_user(user).unlink()
        self.assertTrue(tag.exists())

    def test_27_legitimate_pos_flow_still_generates_tags(self):
        order = self._pay_order(qty=2)
        self.assertEqual(len(order.lines[0].garment_tag_ids), 2)

    # ==================================================================
    # 28-34. Intake notes
    # ==================================================================

    def test_28_authorized_user_can_update_note_while_drop_off(self):
        _ticket, tag = self._ticket_and_tag()
        tag.with_user(self.cashier).action_update_intake_note("handle with care")
        self.assertEqual(tag.intake_note, "handle with care")

    def test_29_authorized_user_can_update_note_while_in_progress(self):
        ticket, tag = self._ticket_and_tag()
        ticket.with_user(self.processor).action_start()
        tag.with_user(self.processor).action_update_intake_note("stain treated")
        self.assertEqual(tag.intake_note, "stain treated")

    def test_30_note_cannot_change_once_ready(self):
        ticket, tag = self._ticket_and_tag()
        ticket.action_start()
        ticket.action_mark_ready()
        with self.assertRaises(UserError):
            tag.with_user(self.processor).action_update_intake_note("too late")

    def test_31_note_cannot_change_once_picked_up(self):
        ticket, tag = self._ticket_and_tag()
        ticket.action_start()
        ticket.action_mark_ready()
        ticket.action_pick_up()
        with self.assertRaises(UserError):
            tag.with_user(self.processor).action_update_intake_note("too late")

    def test_32_manager_cannot_bypass_lifecycle_lock(self):
        ticket, tag = self._ticket_and_tag()
        ticket.action_start()
        ticket.action_mark_ready()
        with self.assertRaises(UserError):
            tag.with_user(self.manager).action_update_intake_note("manager override")

    def test_33_direct_write_cannot_bypass_note_authorization(self):
        """Same rules whether reached via action_update_intake_note() or a
        raw write({'intake_note': ...}) - both funnel through write()."""
        _ticket, tag = self._ticket_and_tag()
        with self.assertRaises(AccessError):
            tag.with_user(self.pickup_staff).write({"intake_note": "sneaky"})

    def test_33b_small_shop_staff_with_process_and_pickup_can_edit_notes(self):
        """Holding Can Pickup alongside Can Process must not lose note
        access - only a Can-Pickup-only user is restricted."""
        _ticket, tag = self._ticket_and_tag()
        tag.with_user(self.small_shop_staff).action_update_intake_note("ok")
        self.assertEqual(tag.intake_note, "ok")

    def test_34_cross_company_note_edit_denied(self):
        _ticket, tag = self._ticket_and_tag()
        with self.assertRaises(AccessError):
            tag.with_user(self.other_company_manager).write({"intake_note": "denied"})

    # ==================================================================
    # 35-39. Event security
    # ==================================================================

    def test_35_36_37_no_role_can_create_write_or_unlink_event(self):
        ticket, _tag = self._ticket_and_tag()
        event = self.env["dry_cleaning.event"].search([("ticket_id", "=", ticket.id)])
        for user in (self.cashier, self.processor, self.pickup_staff, self.manager):
            with self.assertRaises(AccessError):
                self.env["dry_cleaning.event"].with_user(user).create({
                    "ticket_id": ticket.id, "event_type": "in_progress",
                })
            with self.assertRaises(UserError):
                event.with_user(user).write({"note": "tamper"})
            with self.assertRaises(UserError):
                event.with_user(user).unlink()

    def test_38_workflow_transition_still_creates_event(self):
        ticket, _tag = self._ticket_and_tag()
        ticket.with_user(self.processor).action_start()
        events = self.env["dry_cleaning.event"].search([
            ("ticket_id", "=", ticket.id), ("event_type", "=", "in_progress"),
        ])
        self.assertEqual(len(events), 1)

    def test_39_actor_attribution_remains_real_capability_user(self):
        ticket, _tag = self._ticket_and_tag()
        ticket.with_user(self.processor).action_start()
        event = self.env["dry_cleaning.event"].search([
            ("ticket_id", "=", ticket.id), ("event_type", "=", "in_progress"),
        ])
        self.assertEqual(event.user_id, self.processor)
        self.assertNotEqual(event.user_id.id, odoo.SUPERUSER_ID)

    # ==================================================================
    # 40-47. Printing
    # ==================================================================

    def test_40_41_base_user_can_initial_print_and_bookkeeping_updates(self):
        _ticket, tag = self._ticket_and_tag()
        self.assertFalse(tag.printed)
        tag.with_user(self.cashier).action_print_garment_tags()
        self.assertTrue(tag.printed)
        self.assertTrue(tag.printed_date)

    def test_42_base_user_without_reprint_cannot_reprint(self):
        _ticket, tag = self._ticket_and_tag()
        tag.action_print_garment_tags()  # initial print, default user
        with self.assertRaises(AccessError):
            tag.with_user(self.cashier).action_print_garment_tags()

    def test_43_reprint_capability_user_can_reprint(self):
        _ticket, tag = self._ticket_and_tag()
        tag.action_print_garment_tags()
        tag.with_user(self.reprint_staff).action_print_garment_tags()
        self.assertTrue(tag.printed)

    def test_44_manager_can_reprint(self):
        _ticket, tag = self._ticket_and_tag()
        tag.action_print_garment_tags()
        tag.with_user(self.manager).action_print_garment_tags()
        self.assertTrue(tag.printed)

    def test_45_direct_method_rpc_cannot_bypass_reprint_authorization(self):
        _ticket, tag = self._ticket_and_tag()
        tag.action_print_garment_tags()
        with self.assertRaises(AccessError):
            self.env["dry_cleaning.garment_tag"].with_user(self.cashier).browse(
                tag.id
            ).action_print_garment_tags()

    def test_46_mixed_batch_with_one_already_printed_denied_for_base_user(self):
        order = self._pay_order(qty=2)
        tags = order.lines[0].garment_tag_ids
        tags[0].action_print_garment_tags()  # one tag already printed
        self.assertFalse(tags[1].printed)
        with self.assertRaises(AccessError):
            tags.with_user(self.cashier).action_print_garment_tags()
        # Nothing was written - the unprinted tag must still be unprinted.
        tags.invalidate_recordset()
        self.assertFalse(tags[1].printed)

    def test_47_printing_creates_no_workflow_events(self):
        _ticket, tag = self._ticket_and_tag()
        ticket = _ticket
        events_before = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id)]
        )
        tag.with_user(self.cashier).action_print_garment_tags()
        tag.with_user(self.reprint_staff).action_print_garment_tags()
        events_after = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id)]
        )
        self.assertEqual(events_before, events_after)

    # ==================================================================
    # 48-49. Product configuration
    # ==================================================================

    def test_48_dry_cleaning_capability_alone_grants_no_product_admin(self):
        product = self.dry_cleaning_product
        for user in (self.cashier, self.processor, self.manager):
            with self.assertRaises(AccessError):
                product.with_user(user).write({"list_price": 999.0})

    def test_49_requires_garment_tag_protected_by_normal_product_access(self):
        product = self.dry_cleaning_product
        for user in (self.cashier, self.manager):
            with self.assertRaises(AccessError):
                product.with_user(user).write({"requires_garment_tag": False})

    # ==================================================================
    # 50-55. Multi-company
    # ==================================================================

    def test_50_51_user_and_capability_groups_remain_company_isolated(self):
        ticket, tag = self._ticket_and_tag()
        # .sudo(): this class's env.user has its own company_ids narrowed
        # to company_1 only (see setUpClass), so it is not itself allowed
        # to provision a company_2 user - a res.users multi-company record
        # rule unrelated to what this test is actually about (dry-cleaning
        # company isolation, not who may create cross-company logins).
        cross_company_user = self.env["res.users"].sudo().create({
            "name": "Cross Company Processor",
            "login": "stage6_cross_company_processor",
            "company_id": self.company_2.id,
            "company_ids": [(6, 0, self.company_2.ids)],
            "group_ids": [(6, 0, (
                self.group_user | self.group_can_process | self.env.ref("base.group_user")
            ).ids)],
        })
        with self.assertRaises(AccessError):
            ticket.with_user(cross_company_user).read(["name"])
        with self.assertRaises(AccessError):
            tag.with_user(cross_company_user).read(["name"])

    def test_52_manager_remains_company_isolated(self):
        ticket, _tag = self._ticket_and_tag()
        with self.assertRaises(AccessError):
            ticket.with_user(self.other_company_manager).read(["name"])

    def test_53_cross_company_workflow_method_call_denied(self):
        ticket, _tag = self._ticket_and_tag()
        with self.assertRaises(AccessError):
            self.env["dry_cleaning.ticket"].with_user(
                self.other_company_manager
            ).browse(ticket.id).action_start()

    def test_54_cross_company_printing_denied(self):
        _ticket, tag = self._ticket_and_tag()
        with self.assertRaises(AccessError):
            self.env["dry_cleaning.garment_tag"].with_user(
                self.other_company_manager
            ).browse(tag.id).action_print_garment_tags()

    def test_55_cross_company_barcode_lookup_finds_nothing(self):
        _ticket, tag = self._ticket_and_tag()
        info = self.env["dry_cleaning.garment_tag"].with_user(
            self.other_company_manager
        ).lookup_by_barcode(tag.barcode)
        self.assertFalse(info)

    # ==================================================================
    # 56-60. Regression
    # ==================================================================

    def test_56_standard_non_dry_cleaning_transaction_unaffected(self):
        order = self._pay_order(product=self.twenty_dollars_no_tax, qty=2, partner=False)
        self.assertEqual(order.state, "paid")
        self.assertFalse(order.dry_cleaning_ticket_id)

    def test_57_dry_cleaning_transaction_with_customer_still_succeeds(self):
        order = self._pay_order()
        self.assertEqual(order.state, "paid")
        self.assertTrue(order.dry_cleaning_ticket_id)
        self.assertTrue(order.lines[0].garment_tag_ids)

    def test_58_refund_behavior_unchanged(self):
        order, refund = self.create_backend_pos_order({
            "line_data": [{"product_id": self.dry_cleaning_product.product_variant_id.id, "qty": 1}],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
            "refund_data": [{"payment_method_id": self.cash_payment_method.id}],
            "order_data": {"partner_id": self.partner_adgu.id},
        })
        self.assertTrue(order.dry_cleaning_ticket_id)
        self.assertFalse(refund.dry_cleaning_ticket_id)

    def test_59_event_immutability_unchanged(self):
        ticket, _tag = self._ticket_and_tag()
        event = self.env["dry_cleaning.event"].search([("ticket_id", "=", ticket.id)])
        with self.assertRaises(UserError):
            event.sudo().write({"note": "tampering"})
        with self.assertRaises(UserError):
            event.sudo().unlink()

    def test_60_stale_transition_ui_behavior_unchanged(self):
        ticket, _tag = self._ticket_and_tag()
        ticket.with_user(self.manager).action_start()
        ticket.with_user(self.manager).action_mark_ready()
        ticket.with_user(self.manager).action_pick_up()
        result = ticket.with_user(self.manager).action_pick_up_ui()
        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["tag"], "display_notification")
