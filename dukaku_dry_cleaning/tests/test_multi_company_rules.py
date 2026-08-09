# -*- coding: utf-8 -*-
import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest
from odoo.exceptions import AccessError


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningMultiCompanyRules(CommonPosTest):
    """dry_cleaning.ticket / dry_cleaning.garment_tag / dry_cleaning.event
    must not be readable or writable across company boundaries (Stage 2
    remediation, extended in Stage 3 to cover the event model).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dry_cleaning_product = cls.ten_dollars_no_tax
        cls.dry_cleaning_product.requires_garment_tag = True

        cls.company_2 = cls.setup_other_company()["company"]
        # setup_other_company() grants the shared test user (self.env.user)
        # access to company_2 as a side effect; undo that so order/tax
        # creation below stays scoped to company_1 as expected, keeping
        # company_2 exclusively reachable through other_company_user.
        cls.env.user.company_ids = [(6, 0, cls.env.company.ids)]
        cls.other_company_user = cls.env["res.users"].create({
            "name": "Other Company Dry Cleaning Manager",
            "login": "dry_cleaning_other_company_user",
            "company_id": cls.company_2.id,
            "company_ids": [(6, 0, cls.company_2.ids)],
            "group_ids": [(6, 0, (
                cls.env.ref("dukaku_dry_cleaning.group_dry_cleaning_manager")
                | cls.env.ref("point_of_sale.group_pos_manager")
            ).ids)],
        })

    def test_cross_company_ticket_and_tag_access_denied(self):
        order, _refund = self.create_backend_pos_order({
            "line_data": [{"product_id": self.dry_cleaning_product.product_variant_id.id, "qty": 1}],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
            "order_data": {"partner_id": self.partner_adgu.id},
        })
        ticket = order.dry_cleaning_ticket_id
        tag = order.lines[0].garment_tag_ids
        self.assertTrue(ticket, "setup should have produced a ticket")
        self.assertTrue(tag, "setup should have produced a garment tag")

        Ticket = self.env["dry_cleaning.ticket"].with_user(self.other_company_user)
        GarmentTag = self.env["dry_cleaning.garment_tag"].with_user(self.other_company_user)

        # Cross-company records must not show up in a search...
        self.assertFalse(Ticket.search([("id", "=", ticket.id)]))
        self.assertFalse(GarmentTag.search([("id", "=", tag.id)]))

        # ...nor be reachable for read or write by id. Neither 'state' nor
        # 'name' is used as the write probe: both are unconditionally
        # guarded identity fields now (see test_dry_cleaning_event.py and
        # test_write_surface_hardening.py), so writing either would raise
        # UserError from that guard before ever reaching the record-rule
        # check this test is actually about. An empty-dict write touches
        # no field at all, so it isolates the record-rule check cleanly -
        # confirmed to still raise AccessError (Odoo's write() enforces
        # record rules on the browsed ids regardless of vals content).
        with self.assertRaises(AccessError):
            Ticket.browse(ticket.id).read(["name"])
        with self.assertRaises(AccessError):
            Ticket.browse(ticket.id).write({})
        with self.assertRaises(AccessError):
            GarmentTag.browse(tag.id).read(["name"])
        with self.assertRaises(AccessError):
            GarmentTag.browse(tag.id).write({"intake_note": "denied"})

    def test_cross_company_event_read_denied(self):
        order, _refund = self.create_backend_pos_order({
            "line_data": [{"product_id": self.dry_cleaning_product.product_variant_id.id, "qty": 1}],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
            "order_data": {"partner_id": self.partner_adgu.id},
        })
        event = self.env["dry_cleaning.event"].search(
            [("ticket_id", "=", order.dry_cleaning_ticket_id.id)]
        )
        self.assertTrue(event, "paying the order should have logged the initial drop_off event")

        Event = self.env["dry_cleaning.event"].with_user(self.other_company_user)

        # Cross-company events must not show up in a search...
        self.assertFalse(Event.search([("id", "=", event.id)]))
        # ...nor be reachable for read by id.
        with self.assertRaises(AccessError):
            Event.browse(event.id).read(["event_type"])
