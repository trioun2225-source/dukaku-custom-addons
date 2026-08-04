# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class DryCleaningOrder(models.Model):
    _name = "dry.cleaning.order"
    _description = "Dry Cleaning Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_order desc, id desc"

    name = fields.Char(
        required=True, copy=False, readonly=True, default=lambda self: _("New")
    )
    barcode = fields.Char(copy=False, index=True)
    partner_id = fields.Many2one(
        "res.partner", string="Customer", required=True, tracking=True
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id", store=True, readonly=True
    )

    date_order = fields.Datetime(default=fields.Datetime.now, required=True)
    date_expected = fields.Datetime(string="Promised Ready Date")
    date_ready = fields.Datetime(readonly=True, copy=False)
    date_delivered = fields.Datetime(readonly=True, copy=False)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("in_progress", "In Progress"),
            ("ready", "Ready for Pickup"),
            ("delivered", "Delivered"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        copy=False,
        tracking=True,
    )

    line_ids = fields.One2many("dry.cleaning.order.line", "order_id", copy=True)
    amount_total = fields.Monetary(
        compute="_compute_amount_total",
        store=True,
        currency_field="currency_id",
    )

    notes = fields.Text()
    pos_order_id = fields.Many2one(
        "pos.order",
        string="POS Order",
        readonly=True,
        copy=False,
        help="Linked once this order is paid through the Point of Sale.",
    )
    active = fields.Boolean(default=True)

    _barcode_uniq = models.Constraint("unique(barcode)", "Barcode must be unique.")

    @api.depends("line_ids.subtotal")
    def _compute_amount_total(self):
        for order in self:
            order.amount_total = sum(order.line_ids.mapped("subtotal"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("dry.cleaning.order")
                    or _("New")
                )
        return super().create(vals_list)

    def action_confirm(self):
        self.filtered(lambda o: o.state == "draft").write({"state": "confirmed"})

    def action_start(self):
        self.filtered(lambda o: o.state == "confirmed").write({"state": "in_progress"})

    def action_ready(self):
        for order in self.filtered(lambda o: o.state == "in_progress"):
            order.write({"state": "ready", "date_ready": fields.Datetime.now()})

    def action_deliver(self):
        for order in self.filtered(lambda o: o.state == "ready"):
            order.write({"state": "delivered", "date_delivered": fields.Datetime.now()})

    def action_cancel(self):
        self.filtered(lambda o: o.state not in ("delivered", "cancelled")).write(
            {"state": "cancelled"}
        )

    def action_reset_draft(self):
        self.write({"state": "draft"})
