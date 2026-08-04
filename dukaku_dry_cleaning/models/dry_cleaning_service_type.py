# -*- coding: utf-8 -*-
from odoo import api, fields, models


class DryCleaningServiceType(models.Model):
    _name = "dry.cleaning.service.type"
    _description = "Dry Cleaning Service Type"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, help="Short internal code, e.g. WASH, DRYCLEAN, IRON.")
    sequence = fields.Integer(default=10)
    default_price = fields.Monetary(
        string="Default Price",
        currency_field="currency_id",
        required=True,
        default=0.0,
        help="Default price applied to a new order line using this service. Editable per line.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        required=True,
    )
    active = fields.Boolean(default=True)

    _code_company_uniq = models.Constraint(
        "unique(code, company_id)",
        "Service type code must be unique per company.",
    )
    _default_price_non_negative = models.Constraint(
        "CHECK(default_price >= 0)",
        "Default price cannot be negative.",
    )
