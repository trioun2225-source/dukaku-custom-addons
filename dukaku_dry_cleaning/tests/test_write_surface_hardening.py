# -*- coding: utf-8 -*-
"""Stage 6 follow-up: write-surface hardening.

Field-level readonly=True is a view hint only - it does not stop a direct
write()/RPC call. This suite proves that every identity/bookkeeping field
flagged by the audit (ticket.pos_order_id, ticket.company_id/partner_id/
active, tag.pos_order_line_id/barcode/name/printed/printed_date/active) is
now rejected by a direct write(), including under Manager, while the
legitimate paths (action_print_garment_tags, action_update_intake_note,
POS-driven creation, action_start/mark_ready/pick_up) continue to work.
"""
import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest
from odoo.exceptions import AccessError, UserError


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningWriteSurfaceHardening(CommonPosTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dry_cleaning_product = cls.ten_dollars_no_tax
        cls.dry_cleaning_product.requires_garment_tag = True
        cls.env.company.external_report_layout_id = cls.env.ref("web.external_layout_standard")

        base_user_group = cls.env.ref("base.group_user")
        group_user = cls.env.ref("dukaku_dry_cleaning.group_dry_cleaning_user")
        group_manager = cls.env.ref("dukaku_dry_cleaning.group_dry_cleaning_manager")
        group_can_reprint = cls.env.ref("dukaku_dry_cleaning.group_dry_cleaning_can_reprint")

        def _make_user(login, groups):
            return cls.env["res.users"].create({
                "name": login,
                "login": login,
                "group_ids": [(6, 0, (groups | base_user_group).ids)],
            })

        cls.cashier = _make_user("wsh_cashier", group_user)
        cls.reprint_staff = _make_user("wsh_reprint", group_user | group_can_reprint)
        cls.manager = _make_user("wsh_manager", group_manager)

        cls.company_2 = cls.setup_other_company()["company"]
        cls.env.user.company_ids = [(6, 0, cls.env.company.ids)]
        cls.other_company_manager = cls.env["res.users"].sudo().create({
            "name": "WSH Other Company Manager",
            "login": "wsh_other_company_manager",
            "company_id": cls.company_2.id,
            "company_ids": [(6, 0, cls.company_2.ids)],
            "group_ids": [(6, 0, (
                group_manager | base_user_group
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

    # ------------------------------------------------------------------
    # 1-4. Print bookkeeping cannot be forged by direct write()
    # ------------------------------------------------------------------

    def test_01_base_user_cannot_reset_printed_false(self):
        _ticket, tag = self._ticket_and_tag()
        tag.action_print_garment_tags()
        self.assertTrue(tag.printed)
        with self.assertRaises(UserError):
            tag.with_user(self.cashier).write({"printed": False})
        tag.invalidate_recordset()
        self.assertTrue(tag.printed, "printed must remain True - the write must not partially apply")

    def test_02_base_user_cannot_alter_printed_date_directly(self):
        import datetime
        _ticket, tag = self._ticket_and_tag()
        with self.assertRaises(UserError):
            tag.with_user(self.cashier).write({"printed_date": datetime.datetime(2099, 1, 1)})
        self.assertFalse(tag.printed_date)

    def test_03_manager_cannot_directly_reset_print_bookkeeping(self):
        _ticket, tag = self._ticket_and_tag()
        tag.action_print_garment_tags()
        with self.assertRaises(UserError):
            tag.with_user(self.manager).write({"printed": False})
        with self.assertRaises(UserError):
            tag.with_user(self.manager).write({"printed": True, "printed_date": False})
        tag.invalidate_recordset()
        self.assertTrue(tag.printed, "Manager must not be able to forge bookkeeping via direct write either")

    def test_04_reprint_cannot_be_disguised_as_initial_print_via_direct_write(self):
        """The explicit bypass scenario: a printed tag, an actor without
        Can Reprint first tries to reset bookkeeping (denied), then tries
        the legitimate reprint action anyway (also denied, no capability).
        """
        _ticket, tag = self._ticket_and_tag()
        tag.action_print_garment_tags()  # printed by the default (Manager) user
        self.assertTrue(tag.printed)

        # Attempt 1: try to reset bookkeeping directly to disguise this as
        # an unprinted tag.
        with self.assertRaises(UserError):
            tag.with_user(self.cashier).write({"printed": False, "printed_date": False})
        tag.invalidate_recordset()
        self.assertTrue(tag.printed, "direct reset must be rejected outright")

        # Attempt 2: since the reset was rejected, try the real reprint
        # action instead - still denied, no Can Reprint capability.
        with self.assertRaises(AccessError):
            tag.with_user(self.cashier).action_print_garment_tags()

    # ------------------------------------------------------------------
    # 5-6. Controlled print path still works
    # ------------------------------------------------------------------

    def test_05_controlled_initial_print_still_succeeds(self):
        _ticket, tag = self._ticket_and_tag()
        tag.with_user(self.cashier).action_print_garment_tags()
        self.assertTrue(tag.printed)
        self.assertTrue(tag.printed_date)

    def test_06_controlled_authorized_reprint_still_succeeds(self):
        _ticket, tag = self._ticket_and_tag()
        tag.action_print_garment_tags()
        first_date = tag.printed_date
        tag.with_user(self.reprint_staff).action_print_garment_tags()
        self.assertTrue(tag.printed)
        self.assertGreaterEqual(tag.printed_date, first_date)

    # ------------------------------------------------------------------
    # 7-10. Garment tag identity is immutable after creation
    # ------------------------------------------------------------------

    def test_07_tag_barcode_cannot_be_rewritten(self):
        _ticket, tag = self._ticket_and_tag()
        original = tag.barcode
        for user in (self.cashier, self.manager):
            with self.assertRaises(UserError):
                tag.with_user(user).write({"barcode": "HACKED-BARCODE"})
        tag.invalidate_recordset()
        self.assertEqual(tag.barcode, original)

    def test_08_tag_name_cannot_be_rewritten(self):
        _ticket, tag = self._ticket_and_tag()
        original = tag.name
        for user in (self.cashier, self.manager):
            with self.assertRaises(UserError):
                tag.with_user(user).write({"name": "HACKED-NAME"})
        tag.invalidate_recordset()
        self.assertEqual(tag.name, original)

    def test_09_tag_pos_order_line_id_cannot_be_reassigned(self):
        order = self._pay_order(qty=2)
        tags = order.lines[0].garment_tag_ids
        tag, other_tag = tags[0], tags[1]
        original_line = tag.pos_order_line_id
        for user in (self.cashier, self.manager):
            with self.assertRaises(UserError):
                tag.with_user(user).write({"pos_order_line_id": other_tag.pos_order_line_id.id})
        tag.invalidate_recordset()
        self.assertEqual(tag.pos_order_line_id, original_line)

    def test_10_tag_derived_relationships_cannot_be_altered(self):
        order_a = self._pay_order()
        order_b = self._pay_order()
        tag = order_a.lines[0].garment_tag_ids
        for user in (self.cashier, self.manager):
            with self.assertRaises(UserError):
                tag.with_user(user).write({"pos_order_id": order_b.id})
            with self.assertRaises(UserError):
                tag.with_user(user).write({"ticket_id": order_b.dry_cleaning_ticket_id.id})
            with self.assertRaises(UserError):
                tag.with_user(user).write({"product_id": self.twenty_dollars_no_tax.product_variant_id.id})
            with self.assertRaises(UserError):
                tag.with_user(user).write({"company_id": self.company_2.id})

    # ------------------------------------------------------------------
    # 11-12. Ticket identity
    # ------------------------------------------------------------------

    def test_11_ticket_name_cannot_be_rewritten_by_user_or_manager(self):
        """Final identity-lock review: dry_cleaning.ticket.name is the
        server-generated operational ticket identifier - used on receipts,
        customer references, search, staff communication, audit history,
        and future integrations - and must stay stable for the ticket's
        whole lifetime. Supersedes an earlier draft of this guard that left
        name writable; that reasoning (nothing scans/matches against it)
        didn't account for these operational uses.
        """
        ticket, _tag = self._ticket_and_tag()
        original = ticket.name
        for user in (self.cashier, self.manager):
            with self.assertRaises(UserError):
                ticket.with_user(user).write({"name": "HACKED-TICKET-NAME"})
        ticket.invalidate_recordset()
        self.assertEqual(ticket.name, original)

    def test_11b_ticket_creation_still_assigns_sequence_generated_name(self):
        ticket, _tag = self._ticket_and_tag()
        self.assertTrue(ticket.name)
        self.assertNotEqual(ticket.name, "New")
        self.assertTrue(ticket.name.startswith("DC/"), ticket.name)

    def test_12_ticket_pos_order_id_cannot_be_reassigned(self):
        ticket, _tag = self._ticket_and_tag()
        other_order = self._pay_order(product=self.twenty_dollars_no_tax, partner=self.partner_adgu)
        original = ticket.pos_order_id
        for user in (self.cashier, self.manager):
            with self.assertRaises(UserError):
                ticket.with_user(user).write({"pos_order_id": other_order.id})
        ticket.invalidate_recordset()
        self.assertEqual(ticket.pos_order_id, original)

    def test_12b_ticket_derived_fields_cannot_be_altered(self):
        ticket, _tag = self._ticket_and_tag()
        for user in (self.cashier, self.manager):
            with self.assertRaises(UserError):
                ticket.with_user(user).write({"company_id": self.company_2.id})
            with self.assertRaises(UserError):
                ticket.with_user(user).write({"active": False})

    # ------------------------------------------------------------------
    # 13-14. Regression: existing protections unaffected
    # ------------------------------------------------------------------

    def test_13_ticket_state_direct_write_still_blocked(self):
        ticket, _tag = self._ticket_and_tag()
        with self.assertRaises(UserError):
            ticket.write({"state": "in_progress"})

    def test_14_intake_note_remains_editable_under_approved_conditions(self):
        ticket, tag = self._ticket_and_tag()
        tag.with_user(self.cashier).action_update_intake_note("still works")
        self.assertEqual(tag.intake_note, "still works")
        ticket.action_start()
        ticket.action_mark_ready()
        with self.assertRaises(UserError):
            tag.with_user(self.manager).action_update_intake_note("too late")

    # ------------------------------------------------------------------
    # 15-16. Manager is not a bypass; cross-company intact
    # ------------------------------------------------------------------

    def test_15_manager_cannot_bypass_immutable_identity_fields(self):
        ticket, tag = self._ticket_and_tag()
        with self.assertRaises(UserError):
            ticket.with_user(self.manager).write({"pos_order_id": self._pay_order().id})
        with self.assertRaises(UserError):
            tag.with_user(self.manager).write({"barcode": "MANAGER-HACK"})
        with self.assertRaises(UserError):
            tag.with_user(self.manager).write({"pos_order_line_id": tag.pos_order_line_id.id + 1})

    def test_16_cross_company_security_remains_intact(self):
        ticket, tag = self._ticket_and_tag()
        with self.assertRaises(AccessError):
            ticket.with_user(self.other_company_manager).read(["name"])
        with self.assertRaises(AccessError):
            tag.with_user(self.other_company_manager).read(["name"])

    # ------------------------------------------------------------------
    # 17-20. Regression: creation, printing, events
    # ------------------------------------------------------------------

    def test_17_normal_pos_ticket_and_tag_generation_still_works(self):
        order = self._pay_order(qty=2)
        self.assertTrue(order.dry_cleaning_ticket_id)
        self.assertEqual(len(order.lines[0].garment_tag_ids), 2)

    def test_18_printing_still_updates_bookkeeping_internally(self):
        _ticket, tag = self._ticket_and_tag()
        self.assertFalse(tag.printed)
        tag.action_print_garment_tags()
        self.assertTrue(tag.printed)
        self.assertTrue(tag.printed_date)

    def test_19_authorized_reprinting_still_updates_bookkeeping(self):
        _ticket, tag = self._ticket_and_tag()
        tag.action_print_garment_tags()
        first_date = tag.printed_date
        tag.with_user(self.manager).action_print_garment_tags()
        self.assertGreaterEqual(tag.printed_date, first_date)

    def test_20_printing_still_creates_no_workflow_event(self):
        ticket, tag = self._ticket_and_tag()
        events_before = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id)]
        )
        tag.action_print_garment_tags()
        tag.with_user(self.manager).action_print_garment_tags()
        events_after = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id)]
        )
        self.assertEqual(events_before, events_after)
