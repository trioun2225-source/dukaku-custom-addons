# -*- coding: utf-8 -*-
"""Stage 8B: the Dry Cleaning Operations Workspace's read-only,
cursor-based synchronization feed (dry_cleaning.ticket._ops_read_sync).

Deliberately separate from every existing Stage 8/8A offline-sync test:
this is a READ-ONLY discovery mechanism (a processing device learning
about tickets/garments it did not itself create or mutate), not part of
Stage 8A's mutation architecture - nothing here writes anything, and
nothing in dukaku_offline is touched or imported.
"""
import inspect

import odoo
from odoo.addons.point_of_sale.tests.common import CommonPosTest
from odoo.exceptions import AccessError


@odoo.tests.tagged("post_install", "-at_install")
class TestDryCleaningOpsReadSync(CommonPosTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dry_cleaning_product = cls.ten_dollars_no_tax
        cls.dry_cleaning_product.requires_garment_tag = True

        base_user_group = cls.env.ref("base.group_user")
        group_can_process = cls.env.ref("dukaku_dry_cleaning.group_dry_cleaning_can_process")
        group_manager = cls.env.ref("dukaku_dry_cleaning.group_dry_cleaning_manager")

        cls.cashier = cls.env["res.users"].create({
            "name": "Ops Sync Cashier", "login": "ops_sync_cashier",
            "group_ids": [(6, 0, base_user_group.ids)],
        })
        cls.processor = cls.env["res.users"].create({
            "name": "Ops Sync Processor", "login": "ops_sync_processor",
            "group_ids": [(6, 0, (base_user_group | group_can_process).ids)],
        })
        cls.manager = cls.env["res.users"].create({
            "name": "Ops Sync Manager", "login": "ops_sync_manager",
            "group_ids": [(6, 0, (base_user_group | group_manager).ids)],
        })

        cls.company_2 = cls.setup_other_company()["company"]
        cls.env.user.company_ids = [(6, 0, cls.env.company.ids)]
        cls.other_company_processor = cls.env["res.users"].create({
            "name": "Ops Sync Other Company Processor",
            "login": "ops_sync_other_company_processor",
            "company_id": cls.company_2.id,
            "company_ids": [(6, 0, cls.company_2.ids)],
            "group_ids": [(6, 0, (base_user_group | group_can_process).ids)],
        })

    def _pay_order(self, qty=1, partner=None):
        order, _refund = self.create_backend_pos_order({
            "line_data": [{
                "product_id": self.dry_cleaning_product.product_variant_id.id, "qty": qty,
            }],
            "payment_data": [{"payment_method_id": self.cash_payment_method.id}],
            "order_data": {"partner_id": (partner or self.partner_adgu).id},
        })
        return order

    def _sync(self, user, cursor=None):
        return self.env["dry_cleaning.ticket"].with_user(user)._ops_read_sync(cursor=cursor)

    # -- 1: processing user can request allowed cache data -----------------

    def test_01_processing_user_can_request_allowed_cache_data(self):
        order = self._pay_order()
        result = self._sync(self.processor)
        ticket_ids = {t["ticket_id"] for t in result["tickets"]}
        self.assertIn(order.dry_cleaning_ticket_id.id, ticket_ids)

    # -- 2: unauthorized user cannot ----------------------------------------

    def test_02_unauthorized_user_cannot_read_sync(self):
        self._pay_order()
        with self.assertRaises(AccessError):
            self._sync(self.cashier)

    # -- 3: cross-company data excluded --------------------------------------

    def test_03_cross_company_data_excluded(self):
        order = self._pay_order()
        result = self._sync(self.other_company_processor)
        ticket_ids = {t["ticket_id"] for t in result["tickets"]}
        self.assertNotIn(order.dry_cleaning_ticket_id.id, ticket_ids)

    # -- 4: new ticket appears -----------------------------------------------

    def test_04_new_ticket_appears_in_read_sync(self):
        cursor = self._sync(self.processor)["cursor"]
        order = self._pay_order()
        second = self._sync(self.processor, cursor=cursor)
        ticket_ids = {t["ticket_id"] for t in second["tickets"]}
        self.assertIn(order.dry_cleaning_ticket_id.id, ticket_ids)

    # -- 5: new garment tag appears -------------------------------------------

    def test_05_new_garment_tag_appears_in_read_sync(self):
        cursor = self._sync(self.processor)["cursor"]
        order = self._pay_order()
        tag = order.lines[0].garment_tag_ids
        second = self._sync(self.processor, cursor=cursor)
        garment_ids = {g["garment_tag_id"] for g in second["garments"]}
        self.assertIn(tag.id, garment_ids)

    # -- 6: state change appears ---------------------------------------------

    def test_06_state_change_appears_in_read_sync(self):
        order = self._pay_order()
        ticket = order.dry_cleaning_ticket_id
        cursor = self._sync(self.processor)["cursor"]
        ticket.with_user(self.processor).action_start()
        second = self._sync(self.processor, cursor=cursor)
        by_id = {t["ticket_id"]: t for t in second["tickets"]}
        self.assertEqual(by_id[ticket.id]["state"], "in_progress")

    # -- 7: intake-note change appears ----------------------------------------

    def test_07_intake_note_change_appears_in_read_sync(self):
        order = self._pay_order()
        tag = order.lines[0].garment_tag_ids
        cursor = self._sync(self.processor)["cursor"]
        tag.with_user(self.processor).action_update_intake_note("handle with care")
        second = self._sync(self.processor, cursor=cursor)
        by_id = {g["garment_tag_id"]: g for g in second["garments"]}
        self.assertEqual(by_id[tag.id]["intake_note"], "handle with care")

    # -- 8: cancellation/inactivation representable ---------------------------

    def test_08_inactive_ticket_and_garment_reported_as_inactive(self):
        """dry_cleaning.ticket/garment_tag.active is a frozen Stage 4
        compute (archives automatically when the POS order is cancelled) -
        not something Stage 8B redesigns. A paid order cannot normally be
        moved back to 'cancel' through the ORM (see
        test_dry_cleaning_event.py's own equivalent finding), so this test
        writes the already-computed-style outcome directly, exactly like
        that existing test does, to prove _ops_read_sync faithfully
        surfaces whatever `active` value is stored - not to re-exercise
        _compute_active itself, which is out of scope here.
        """
        order = self._pay_order()
        ticket = order.dry_cleaning_ticket_id
        tag = order.lines[0].garment_tag_ids
        cursor = self._sync(self.processor)["cursor"]

        self.env.cr.execute(
            "UPDATE dry_cleaning_ticket SET active = false, write_date = now() WHERE id = %s",
            (ticket.id,),
        )
        self.env.cr.execute(
            "UPDATE dry_cleaning_garment_tag SET active = false, write_date = now() WHERE id = %s",
            (tag.id,),
        )
        ticket.invalidate_recordset()
        tag.invalidate_recordset()

        second = self._sync(self.processor, cursor=cursor)
        ticket_by_id = {t["ticket_id"]: t for t in second["tickets"]}
        garment_by_id = {g["garment_tag_id"]: g for g in second["garments"]}
        self.assertFalse(ticket_by_id[ticket.id]["active"])
        self.assertFalse(garment_by_id[tag.id]["active"])

    # -- 9: PII/financial fields absent ---------------------------------------

    def test_09_pii_and_financial_fields_absent_from_payload(self):
        order = self._pay_order()
        result = self._sync(self.processor)
        payload_str = str(result).lower()
        for forbidden in ("phone", "email", "street", "iban", "card", "amount_total", "payment"):
            self.assertNotIn(forbidden, payload_str)

        ticket_row = next(
            t for t in result["tickets"] if t["ticket_id"] == order.dry_cleaning_ticket_id.id
        )
        self.assertEqual(
            set(ticket_row.keys()),
            {"ticket_id", "ticket_name", "state", "active", "company_id",
             "customer_name", "server_write_date"},
        )
        garment_row = next(
            g for g in result["garments"] if g["ticket_id"] == order.dry_cleaning_ticket_id.id
        )
        self.assertEqual(
            set(garment_row.keys()),
            {"garment_tag_id", "ticket_id", "barcode", "product_name",
             "intake_note", "active", "server_write_date"},
        )

    # -- 10: no arbitrary model/field access ----------------------------------

    def test_10_no_arbitrary_model_or_field_parameter_exists(self):
        """Closed API surface: only cursor/limit exist - there is no
        model/fields-style parameter to request anything beyond the fixed
        payload shape proven in test_09."""
        sig = inspect.signature(self.env["dry_cleaning.ticket"]._ops_read_sync)
        self.assertEqual(set(sig.parameters), {"cursor", "limit"})

    def test_10b_malformed_cursor_is_ignored_not_trusted(self):
        """A cursor is only ever a string this method itself previously
        produced - a malformed/foreign value must never raise or leak
        anything, just be treated as "no prior position"."""
        result = self._sync(self.processor, cursor="not-a-real-cursor;drop table")
        self.assertIn("tickets", result)
        self.assertIn("garments", result)

    # -- 11: no broad sudo in the read path ------------------------------------

    def test_11_read_sync_model_uses_no_sudo(self):
        import odoo.addons.dukaku_dry_cleaning.models.dry_cleaning_ops_sync as sync_mod
        source = open(sync_mod.__file__).read()
        self.assertNotIn(".sudo(", source)

    def test_11b_read_sync_controller_uses_no_sudo(self):
        import odoo.addons.dukaku_dry_cleaning.controllers.dry_cleaning_ops as ctrl_mod
        source = open(ctrl_mod.__file__).read()
        self.assertNotIn(".sudo(", source)

    # -- 12: manager/process access behaves per frozen roles -------------------

    def test_12_manager_and_processor_allowed_cashier_denied(self):
        order = self._pay_order()
        ticket_id = order.dry_cleaning_ticket_id.id

        manager_result = self._sync(self.manager)
        self.assertIn(ticket_id, {t["ticket_id"] for t in manager_result["tickets"]})

        processor_result = self._sync(self.processor)
        self.assertIn(ticket_id, {t["ticket_id"] for t in processor_result["tickets"]})

        with self.assertRaises(AccessError):
            self._sync(self.cashier)
