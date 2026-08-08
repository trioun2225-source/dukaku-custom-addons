# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    requires_garment_tag = fields.Boolean(
        string="Requires Garment Tag",
        default=False,
        help=(
            "If set, each unit of quantity sold on a POS order line for this "
            "product generates one dry-cleaning garment tag when the order is paid. "
            "Set this on dry-cleaning service products only."
        ),
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        return super()._load_pos_data_fields(config_id) + ["requires_garment_tag"]
