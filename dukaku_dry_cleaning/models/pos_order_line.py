# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    garment_tag_ids = fields.One2many(
        "dry_cleaning.garment_tag", "pos_order_line_id", string="Garment Tags"
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ["garment_tag_ids"]

    def _dry_cleaning_sync_garment_tags(self):
        """Create any garment tags missing from this line's full set, one per
        unit of quantity.

        Idempotent: re-running against a line that already has its full set
        of tags creates nothing further. Lines with zero or negative
        quantity (e.g. refund lines) are skipped rather than raising, since
        a refund should never mint new garment tags.
        """
        self.ensure_one()
        if self.qty <= 0:
            return self.env["dry_cleaning.garment_tag"]

        target = int(self.qty)
        if target != self.qty:
            raise UserError(_(
                "Cannot generate garment tags for %(product)s: quantity %(qty)s "
                "is not a whole number of garments.",
                product=self.product_id.display_name,
                qty=self.qty,
            ))

        GarmentTag = self.env["dry_cleaning.garment_tag"]
        existing = GarmentTag.search_count([("pos_order_line_id", "=", self.id)])
        missing = target - existing
        if missing <= 0:
            return GarmentTag
        return GarmentTag.create([
            {"pos_order_line_id": self.id} for _unused in range(missing)
        ])
