# -*- coding: utf-8 -*-
import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningBarcodeLookupWizard(CommonPosTest):
    """Stage 4: the backend barcode lookup wizard, built entirely on the
    Stage 2 lookup_by_barcode() exact-match lookup - no fuzzy matching, no
    auto-created garments for an unknown scan.
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

    def test_valid_barcode_resolves_correct_garment(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        tag = order.lines[0].garment_tag_ids

        wizard = self.env["dry_cleaning.barcode_lookup"].create({})
        wizard.barcode = tag.barcode
        wizard._onchange_barcode()

        self.assertFalse(wizard.not_found)
        self.assertEqual(wizard.garment_tag_id, tag)
        # The input is cleared immediately so the next scan can go straight in.
        self.assertFalse(wizard.barcode)

    def test_correct_ticket_and_siblings_returned(self):
        order = self._pay_order(self.dry_cleaning_product, 3)
        tags = order.lines[0].garment_tag_ids
        first_tag = tags[0]

        wizard = self.env["dry_cleaning.barcode_lookup"].create({})
        wizard.barcode = first_tag.barcode
        wizard._onchange_barcode()

        self.assertEqual(wizard.ticket_id, order.dry_cleaning_ticket_id)
        self.assertEqual(wizard.partner_id, order.partner_id)
        self.assertEqual(wizard.pos_order_id, order)
        self.assertEqual(set(wizard.sibling_garment_tag_ids.ids), set(tags.ids))

    def test_unknown_barcode_fails_cleanly(self):
        wizard = self.env["dry_cleaning.barcode_lookup"].create({})
        wizard.barcode = "NOT-A-REAL-BARCODE"
        wizard._onchange_barcode()

        self.assertTrue(wizard.not_found)
        self.assertFalse(wizard.garment_tag_id)
        self.assertEqual(wizard.scanned_barcode, "NOT-A-REAL-BARCODE")
        # Never auto-creates anything from an unrecognized scan.
        self.assertFalse(
            self.env["dry_cleaning.garment_tag"].search([("barcode", "=", "NOT-A-REAL-BARCODE")])
        )

    def test_wizard_ticket_actions_call_existing_server_methods(self):
        order = self._pay_order(self.dry_cleaning_product, 1)
        tag = order.lines[0].garment_tag_ids
        ticket = order.dry_cleaning_ticket_id

        wizard = self.env["dry_cleaning.barcode_lookup"].create({})
        wizard.barcode = tag.barcode
        wizard._onchange_barcode()

        wizard.action_ticket_start()
        self.assertEqual(ticket.state, "in_progress")


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningBarcodeLookupCrossCompany(CommonPosTest):
    """Cross-company isolation must hold through the wizard too: it is a
    thin wrapper around the same search the Stage 2/3 multi-company rule
    already protects, exercised here under a different-company user.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dry_cleaning_product = cls.ten_dollars_no_tax
        cls.dry_cleaning_product.requires_garment_tag = True
        cls.company_2 = cls.setup_other_company()["company"]
        cls.env.user.company_ids = [(6, 0, cls.env.company.ids)]
        cls.other_company_user = cls.env["res.users"].create({
            "name": "Other Company Dry Cleaning Manager",
            "login": "dry_cleaning_barcode_other_company_user",
            "company_id": cls.company_2.id,
            "company_ids": [(6, 0, cls.company_2.ids)],
            "group_ids": [(6, 0, (
                cls.env.ref("dukaku_dry_cleaning.group_dry_cleaning_manager")
                | cls.env.ref("point_of_sale.group_pos_manager")
            ).ids)],
        })

    def test_cross_company_barcode_scan_reports_not_found(self):
        order, _refund = self.create_backend_pos_order({
            "line_data": [{"product_id": self.dry_cleaning_product.product_variant_id.id, "qty": 1}],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
            "order_data": {"partner_id": self.partner_adgu.id},
        })
        tag = order.lines[0].garment_tag_ids

        wizard = self.env["dry_cleaning.barcode_lookup"].with_user(
            self.other_company_user
        ).create({})
        wizard.barcode = tag.barcode
        wizard._onchange_barcode()

        self.assertTrue(wizard.not_found)
        self.assertFalse(wizard.garment_tag_id)
