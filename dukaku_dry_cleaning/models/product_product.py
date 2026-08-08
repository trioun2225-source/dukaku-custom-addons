# -*- coding: utf-8 -*-
from odoo import api, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _load_pos_data_fields(self, config):
        """POS order lines reference product.product (not product.template)
        as product_id, and product.product._load_pos_data_fields is an
        independent list from product.template's - so requires_garment_tag
        needs to be added here too for line.product_id.requires_garment_tag
        to actually be available client-side, even though the field itself
        is defined on product.template (product.product exposes it via
        the standard _inherits delegation).
        """
        return super()._load_pos_data_fields(config) + ["requires_garment_tag"]
