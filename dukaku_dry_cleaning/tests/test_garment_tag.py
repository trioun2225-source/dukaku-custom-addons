# -*- coding: utf-8 -*-
import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest
from odoo.exceptions import UserError
from odoo.tools import mute_logger
from psycopg2 import IntegrityError


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningGarmentTag(CommonPosTest):
    """Stage 2 garment tag / barcode tests.

    Reuses CommonPosTest (the same base used by pos_mrp, pos_loyalty, pos_hr,
    etc.) so orders are paid through the real action_pos_order_paid path
    instead of calling internal helpers directly.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dry_cleaning_product = cls.ten_dollars_no_tax
        cls.dry_cleaning_product.requires_garment_tag = True
        # Without a configured layout, report_action() returns the "configure
        # your report layout" onboarding wizard instead of the report action
        # itself (only for admin users, which the test user is).
        cls.env.company.external_report_layout_id = cls.env.ref("web.external_layout_standard")

    def _pay_order(self, product, qty, partner=None):
        order, _refund = self.create_backend_pos_order({
            "line_data": [{"product_id": product.product_variant_id.id, "qty": qty}],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
            # A customer is required (Stage 4) for orders with a qualifying
            # dry-cleaning line; default to a stock CommonPosTest partner so
            # every existing call site keeps working unchanged.
            "order_data": {"partner_id": (partner or self.partner_adgu).id},
        })
        return order

    def test_paid_order_generates_ticket_and_one_tag_per_unit(self):
        order = self._pay_order(self.dry_cleaning_product, 3)
        line = order.lines[0]

        self.assertTrue(order.dry_cleaning_ticket_id, "Paying the order should create a ticket")
        self.assertEqual(len(line.garment_tag_ids), 3)
        for tag in line.garment_tag_ids:
            self.assertEqual(tag.name, tag.barcode, "tag number must match the barcode")
            self.assertEqual(tag.pos_order_id, order)
            self.assertEqual(tag.ticket_id, order.dry_cleaning_ticket_id)
        # Every tag on the same line must have gotten a distinct barcode.
        self.assertEqual(len(set(line.garment_tag_ids.mapped("barcode"))), 3)

    def test_non_dry_cleaning_line_creates_nothing(self):
        order = self._pay_order(self.twenty_dollars_no_tax, 2)
        self.assertFalse(order.dry_cleaning_ticket_id)
        self.assertFalse(order.lines[0].garment_tag_ids)

    def test_refund_order_does_not_create_orphaned_ticket(self):
        """A refund order's lines carry negative qty; even though the product
        requires_garment_tag, the refund order itself must not get its own
        ticket (Stage 2 remediation)."""
        order, refund = self.create_backend_pos_order({
            "line_data": [{"product_id": self.dry_cleaning_product.product_variant_id.id, "qty": 1}],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
            "refund_data": [{"payment_method_id": self.cash_payment_method.id}],
            "order_data": {"partner_id": self.partner_adgu.id},
        })
        self.assertTrue(order.dry_cleaning_ticket_id)
        self.assertFalse(
            refund.dry_cleaning_ticket_id,
            "A refund order must not get its own dry cleaning ticket",
        )
        self.assertFalse(refund.lines.garment_tag_ids)

    def test_tag_generation_is_idempotent(self):
        order = self._pay_order(self.dry_cleaning_product, 2)
        line = order.lines[0]
        self.assertEqual(len(line.garment_tag_ids), 2)

        # Re-running against an already-fully-tagged line creates nothing further.
        line._dry_cleaning_sync_garment_tags()
        self.assertEqual(len(line.garment_tag_ids), 2)

        # Re-running the order-level orchestration is also a no-op.
        order._dry_cleaning_process_order()
        self.assertEqual(len(line.garment_tag_ids), 2)

    def test_ticket_get_or_create_does_not_duplicate(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        ticket = order.dry_cleaning_ticket_id
        ticket_again = self.env["dry_cleaning.ticket"]._get_or_create_for_order(order)
        self.assertEqual(ticket, ticket_again)
        self.assertEqual(len(order.ticket_ids), 1)

    def test_derived_fields_follow_pos_order_line_id(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        line = order.lines[0]
        tag = line.garment_tag_ids

        self.assertEqual(tag.pos_order_id, line.order_id)
        self.assertEqual(tag.ticket_id, line.order_id.dry_cleaning_ticket_id)

        other_order = self._pay_order(self.dry_cleaning_product, 1)
        with self.assertRaises(UserError):
            tag.write({"pos_order_id": other_order.id})
        with self.assertRaises(UserError):
            tag.write({"ticket_id": other_order.dry_cleaning_ticket_id.id})

        # Unaffected by the rejected calls above.
        self.assertEqual(tag.pos_order_id, line.order_id)
        self.assertEqual(tag.ticket_id, line.order_id.dry_cleaning_ticket_id)

    def test_fractional_quantity_raises(self):
        with self.assertRaises(UserError):
            self._pay_order(self.dry_cleaning_product, 1.5)

    def test_barcode_uniqueness_constraint(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        line = order.lines[0]
        existing_tag = line.garment_tag_ids

        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            self.env["dry_cleaning.garment_tag"].create({
                "pos_order_line_id": line.id,
                "barcode": existing_tag.barcode,
                "name": "DUPLICATE",
            })

    def test_lookup_by_barcode(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        tag = order.lines[0].garment_tag_ids

        info = self.env["dry_cleaning.garment_tag"].lookup_by_barcode(tag.barcode)
        self.assertEqual(info["garment_tag_id"], tag.id)
        self.assertEqual(info["ticket_id"], order.dry_cleaning_ticket_id.id)
        self.assertEqual(info["pos_order_id"], order.id)
        self.assertEqual(info["intake_note"], tag.intake_note)

        self.assertFalse(
            self.env["dry_cleaning.garment_tag"].lookup_by_barcode("NOT-A-REAL-BARCODE")
        )

    def test_print_action_marks_printed(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        tag = order.lines[0].garment_tag_ids
        self.assertFalse(tag.printed)

        action = tag.action_print_garment_tags()
        self.assertTrue(tag.printed)
        self.assertTrue(tag.printed_date)
        self.assertEqual(action["report_name"], "dukaku_dry_cleaning.report_dry_cleaning_garment_tag_label_document")
