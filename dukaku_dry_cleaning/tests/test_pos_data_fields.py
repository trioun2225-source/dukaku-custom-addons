# -*- coding: utf-8 -*-
import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningPosDataFields(CommonPosTest):
    """Stage 4: requires_garment_tag and the ticket/garment convenience
    fields must actually be exposed to the POS frontend through the
    standard _load_pos_data_fields extension mechanism - detection stays
    based only on that boolean, never on category/name heuristics.
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

    def test_requires_garment_tag_in_product_product_pos_fields(self):
        fields = self.env["product.product"]._load_pos_data_fields(self.pos_config_usd)
        self.assertIn("requires_garment_tag", fields)

    def test_requires_garment_tag_in_product_template_pos_fields(self):
        fields = self.env["product.template"]._load_pos_data_fields(self.pos_config_usd)
        self.assertIn("requires_garment_tag", fields)

    def test_requires_garment_tag_readable_on_loaded_product_data(self):
        """Not just declared - actually comes back through the real
        product.product read path POS uses at session start."""
        variant = self.dry_cleaning_product.product_variant_id
        data = self.env["product.product"]._load_pos_data_read(variant, self.pos_config_usd)
        self.assertTrue(data)
        self.assertTrue(data[0]["requires_garment_tag"])

    def test_ticket_name_and_garment_count_in_pos_order_fields(self):
        fields = self.env["pos.order"]._load_pos_data_fields(self.pos_config_usd)
        self.assertIn("dry_cleaning_ticket_name", fields)
        self.assertIn("dry_cleaning_garment_tag_count", fields)

    def test_garment_tag_ids_in_pos_order_line_fields(self):
        fields = self.env["pos.order.line"]._load_pos_data_fields(self.pos_config_usd)
        self.assertIn("garment_tag_ids", fields)

    def test_dry_cleaning_order_pos_data_values_are_authoritative(self):
        order = self._pay_order(self.dry_cleaning_product, 2)
        data = self.env["pos.order"]._load_pos_data_read(order, self.pos_config_usd)[0]
        self.assertEqual(data["dry_cleaning_ticket_name"], order.dry_cleaning_ticket_id.name)
        self.assertEqual(data["dry_cleaning_garment_tag_count"], 2)

    def test_non_dry_cleaning_order_pos_data_values_are_empty(self):
        """Regression: an ordinary order must not pick up any dry-cleaning
        receipt/print data."""
        order = self._pay_order(self.twenty_dollars_no_tax, 1)
        data = self.env["pos.order"]._load_pos_data_read(order, self.pos_config_usd)[0]
        self.assertFalse(data["dry_cleaning_ticket_name"])
        self.assertEqual(data["dry_cleaning_garment_tag_count"], 0)
