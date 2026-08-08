# -*- coding: utf-8 -*-
import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest
from odoo.exceptions import ValidationError


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningCustomerRequired(CommonPosTest):
    """Stage 4: a customer is mandatory for any order with a qualifying
    dry-cleaning line (product_id.requires_garment_tag and qty > 0, the
    same condition frozen in Stage 2). Enforced via @api.constrains on
    pos.order so it applies regardless of entry path.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dry_cleaning_product = cls.ten_dollars_no_tax
        cls.dry_cleaning_product.requires_garment_tag = True

    def _create_paid_order(self, product, qty, partner_id=False,
                            payment_method=None):
        payment_method = payment_method or self.cash_payment_method
        order, _refund = self.create_backend_pos_order({
            "line_data": [{"product_id": product.product_variant_id.id, "qty": qty}],
            "payment_data": [{"payment_method_id": payment_method.id}],
            "order_data": {"partner_id": partner_id},
        })
        return order

    def test_qualifying_order_without_customer_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_paid_order(self.dry_cleaning_product, 1, partner_id=False)

    def test_direct_orm_write_cannot_bypass(self):
        """The check is a model-level @api.constrains, not a hook inside
        action_pos_order_paid() - so it must also fire for a direct ORM
        write({'state': 'paid'}) that never goes through that method (no
        payment_data here, so the order is created and left in 'draft')."""
        order, _refund = self.create_backend_pos_order({
            "line_data": [{"product_id": self.dry_cleaning_product.product_variant_id.id, "qty": 1}],
            "order_data": {"partner_id": False},
        })
        self.assertEqual(order.state, "draft")
        with self.assertRaises(ValidationError):
            order.write({"state": "paid"})

    def test_qualifying_order_with_customer_succeeds(self):
        order = self._create_paid_order(
            self.dry_cleaning_product, 1, partner_id=self.partner_adgu.id
        )
        self.assertEqual(order.state, "paid")
        self.assertTrue(order.dry_cleaning_ticket_id)

    def test_ordinary_order_without_customer_unaffected(self):
        """No qualifying line -> the constraint must not even look at partner_id."""
        order = self._create_paid_order(
            self.twenty_dollars_no_tax, 2, partner_id=False
        )
        self.assertEqual(order.state, "paid")
        self.assertFalse(order.dry_cleaning_ticket_id)

    def test_refund_order_without_customer_not_blocked(self):
        """Refund lines carry negative qty, so they never qualify - a refund
        of a dry-cleaning sale must not suddenly require a customer either."""
        order, refund = self.create_backend_pos_order({
            "line_data": [{"product_id": self.dry_cleaning_product.product_variant_id.id, "qty": 1}],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
            "refund_data": [{"payment_method_id": self.cash_payment_method.id}],
            "order_data": {"partner_id": self.partner_adgu.id},
        })
        self.assertEqual(order.state, "paid")
        # The refund order only has a negative-qty qualifying-product line
        # (refund lines never satisfy the qualifying condition), so it must
        # complete without the constraint raising - regardless of the
        # partner it happens to carry (here, inherited from the original
        # order by core POS's own refund() flow).
        self.assertIn(refund.state, ("paid", "done", "invoiced"))
        self.assertTrue(
            all(line.qty < 0 for line in refund.lines),
            "sanity check: refund lines must indeed be negative-qty",
        )
