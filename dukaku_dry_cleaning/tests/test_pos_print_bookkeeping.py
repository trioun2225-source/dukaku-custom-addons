# -*- coding: utf-8 -*-
import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningPosPrintBookkeeping(CommonPosTest):
    """Freeze hardening (Section 2): the POS "Print Garment Labels" button
    calls dry_cleaning.garment_tag.action_print_garment_tags(ids) by RPC -
    the exact same Stage 2 method the backend button already used, invoked
    the same way Odoo's ORM RPC dispatch would (browse ids, call method).

    This replaces the original POS implementation, which called
    report.doAction(xmlId, ids) directly - that path only downloads the PDF
    via /report/download and never touches action_print_garment_tags(), so
    printed/printed_date were silently never updated when printing from POS.
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

    def _pos_print_ids(self, order):
        """Exactly what static/src/app/screens/receipt_screen/receipt_screen.js's
        dryCleaningGarmentTagIds getter collects client-side, and exactly how
        it's invoked: env['dry_cleaning.garment_tag'].browse(ids)."""
        ids = order.lines.garment_tag_ids.ids
        return self.env["dry_cleaning.garment_tag"].browse(ids)

    def test_pos_print_path_returns_valid_report_action(self):
        order = self._pay_order(self.dry_cleaning_product, 2)
        tags = self._pos_print_ids(order)

        action = tags.action_print_garment_tags()

        # Exactly what static/.../receipt_screen.js feeds into downloadReport():
        # needs report_name and context.active_ids to build the download URL.
        self.assertEqual(
            action["report_name"],
            "dukaku_dry_cleaning.report_dry_cleaning_garment_tag_label_document",
        )
        self.assertEqual(set(action["context"]["active_ids"]), set(tags.ids))

    def test_pos_print_path_first_print_updates_bookkeeping(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        tag = self._pos_print_ids(order)
        self.assertFalse(tag.printed)
        self.assertFalse(tag.printed_date)

        tag.action_print_garment_tags()

        self.assertTrue(tag.printed)
        self.assertTrue(tag.printed_date)

    def test_pos_print_path_reprint_updates_printed_date_again(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        tag = self._pos_print_ids(order)

        tag.action_print_garment_tags()
        first_printed_date = tag.printed_date

        tag.action_print_garment_tags()  # reprint via the same POS-facing path

        self.assertTrue(tag.printed)
        self.assertGreaterEqual(tag.printed_date, first_printed_date)

    def test_pos_print_path_barcode_identity_unchanged_on_reprint(self):
        order = self._pay_order(self.dry_cleaning_product, 2)
        tags = self._pos_print_ids(order)
        barcodes_before = tags.mapped("barcode")

        tags.action_print_garment_tags()
        tags.action_print_garment_tags()  # reprint

        tags.invalidate_recordset()
        self.assertEqual(tags.mapped("barcode"), barcodes_before)

    def test_pos_print_path_reprint_creates_no_new_garment_tag(self):
        order = self._pay_order(self.dry_cleaning_product, 2)
        tags = self._pos_print_ids(order)
        ticket = order.dry_cleaning_ticket_id
        count_before = self.env["dry_cleaning.garment_tag"].search_count(
            [("ticket_id", "=", ticket.id)]
        )

        tags.action_print_garment_tags()
        tags.action_print_garment_tags()  # reprint

        count_after = self.env["dry_cleaning.garment_tag"].search_count(
            [("ticket_id", "=", ticket.id)]
        )
        self.assertEqual(count_before, count_after)

    def test_pos_print_path_creates_no_dry_cleaning_event(self):
        order = self._pay_order(self.dry_cleaning_product, 2)
        tags = self._pos_print_ids(order)
        ticket = order.dry_cleaning_ticket_id
        events_before = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id)]
        )

        tags.action_print_garment_tags()
        tags.action_print_garment_tags()  # reprint too

        events_after = self.env["dry_cleaning.event"].search_count(
            [("ticket_id", "=", ticket.id)]
        )
        self.assertEqual(
            events_before, events_after,
            "printing/reprinting from the POS path must never create a dry_cleaning.event",
        )
