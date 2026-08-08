# -*- coding: utf-8 -*-
import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningPrintingStage4(CommonPosTest):
    """Stage 4: batch/reprint garment-label printing at the ticket level.
    Reuses Stage 2's garment_tag.action_print_garment_tags() and its
    printed/printed_date bookkeeping as-is - no separate print-history
    subsystem, no dry_cleaning.event created by printing.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dry_cleaning_product = cls.ten_dollars_no_tax
        cls.dry_cleaning_product.requires_garment_tag = True
        cls.env.company.external_report_layout_id = cls.env.ref("web.external_layout_standard")

    def _pay_order(self, product, qty, partner=None):
        order, _refund = self.create_backend_pos_order({
            "line_data": [{"product_id": product.product_variant_id.id, "qty": qty}],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
            "order_data": {"partner_id": (partner or self.partner_adgu).id},
        })
        return order

    def test_single_label_action_works(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        tag = order.lines[0].garment_tag_ids
        action = tag.action_print_garment_tags()
        self.assertEqual(
            action["report_name"],
            "dukaku_dry_cleaning.report_dry_cleaning_garment_tag_label_document",
        )
        self.assertTrue(tag.printed)

    def test_batch_ticket_label_action_works(self):
        order = self._pay_order(self.dry_cleaning_product, 3)
        ticket = order.dry_cleaning_ticket_id
        tags = order.lines[0].garment_tag_ids
        self.assertEqual(len(tags), 3)

        action = ticket.action_print_garment_tags()

        self.assertEqual(
            action["report_name"],
            "dukaku_dry_cleaning.report_dry_cleaning_garment_tag_label_document",
        )
        for tag in tags:
            self.assertTrue(tag.printed)
            self.assertTrue(tag.printed_date)

    def test_reprint_does_not_create_new_garment_records(self):
        order = self._pay_order(self.dry_cleaning_product, 2)
        ticket = order.dry_cleaning_ticket_id
        count_before = self.env["dry_cleaning.garment_tag"].search_count(
            [("ticket_id", "=", ticket.id)]
        )

        ticket.action_print_garment_tags()
        ticket.action_print_garment_tags()  # reprint

        count_after = self.env["dry_cleaning.garment_tag"].search_count(
            [("ticket_id", "=", ticket.id)]
        )
        self.assertEqual(count_before, count_after)

    def test_reprint_does_not_change_barcode_identity(self):
        order = self._pay_order(self.dry_cleaning_product, 2)
        ticket = order.dry_cleaning_ticket_id
        tags = ticket.garment_tag_ids
        barcodes_before = tags.mapped("barcode")

        ticket.action_print_garment_tags()
        ticket.action_print_garment_tags()  # reprint

        tags.invalidate_recordset()
        self.assertEqual(tags.mapped("barcode"), barcodes_before)

    def test_printed_fields_update_correctly_on_reprint(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        tag = order.lines[0].garment_tag_ids
        self.assertFalse(tag.printed)
        self.assertFalse(tag.printed_date)

        ticket = order.dry_cleaning_ticket_id
        ticket.action_print_garment_tags()
        first_printed_date = tag.printed_date
        self.assertTrue(tag.printed)
        self.assertTrue(first_printed_date)

        ticket.action_print_garment_tags()  # reprint: printed_date reflects the latest print
        self.assertTrue(tag.printed)
        self.assertTrue(tag.printed_date)
        self.assertGreaterEqual(tag.printed_date, first_printed_date)

    def test_printing_creates_no_events(self):
        order = self._pay_order(self.dry_cleaning_product, 2)
        ticket = order.dry_cleaning_ticket_id
        events_before = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id)]
        )

        ticket.action_print_garment_tags()
        ticket.action_print_garment_tags()  # reprint too

        events_after = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id)]
        )
        self.assertEqual(
            events_before, events_after,
            "printing/reprinting must never create a dry_cleaning.event",
        )
