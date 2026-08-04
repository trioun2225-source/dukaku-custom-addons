# -*- coding: utf-8 -*-
from odoo import api, fields, models


class DryCleaningOrderLine(models.Model):
    _name = "dry.cleaning.order.line"
    _description = "Dry Cleaning Order Line"

    order_id = fields.Many2one(
        "dry.cleaning.order",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="order_id.company_id", store=True, index=True
    )
    currency_id = fields.Many2one(related="order_id.currency_id", store=True)

    service_type_id = fields.Many2one(
        "dry.cleaning.service.type",
        string="Service",
        required=True,
    )
    garment_description = fields.Char(
        required=True, help="E.g. 'Blue cotton shirt', 'Winter coat'."
    )
    quantity = fields.Float(default=1.0, required=True)
    price_unit = fields.Monetary(
        string="Unit Price", required=True, currency_field="currency_id"
    )
    subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_subtotal",
        store=True,
        currency_field="currency_id",
    )
    notes = fields.Char(help="Special instructions, stain notes, etc.")

    _quantity_positive = models.Constraint(
        "CHECK(quantity > 0)", "Quantity must be greater than zero."
    )
    _price_non_negative = models.Constraint(
        "CHECK(price_unit >= 0)", "Price cannot be negative."
    )

    @api.depends("quantity", "price_unit")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.onchange("service_type_id")
    def _onchange_service_type_id(self):
        for line in self:
            if line.service_type_id:
                line.price_unit = line.service_type_id.default_price
                if not line.garment_description:
                    line.garment_description = line.service_type_id.name
