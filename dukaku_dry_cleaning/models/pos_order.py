# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PosOrder(models.Model):
    _inherit = "pos.order"

    ticket_ids = fields.One2many(
        "dry_cleaning.ticket", "pos_order_id", string="Dry Cleaning Tickets"
    )
    dry_cleaning_ticket_id = fields.Many2one(
        "dry_cleaning.ticket",
        string="Dry Cleaning Ticket",
        compute="_compute_dry_cleaning_ticket_id",
        store=True,
        index=True,
        help="Convenience singular pointer to this order's ticket - pos_order_id "
             "is unique on dry_cleaning.ticket, so there is at most one.",
    )
    dry_cleaning_ticket_name = fields.Char(
        related="dry_cleaning_ticket_id.name",
        string="Dry Cleaning Ticket Number",
        help="POS-frontend-facing convenience field: the authoritative ticket "
             "number as text, so the POS UI never has to resolve/display an id.",
    )
    dry_cleaning_garment_tag_count = fields.Integer(
        compute="_compute_dry_cleaning_garment_tag_count",
        string="Garment Tag Count",
        help="Number of garment tags generated for this order. Exposed to the "
             "POS frontend so it can decide whether to offer label printing "
             "without guessing eligibility client-side.",
    )

    @api.depends("ticket_ids")
    def _compute_dry_cleaning_ticket_id(self):
        for order in self:
            order.dry_cleaning_ticket_id = order.ticket_ids[:1]

    @api.depends("lines.garment_tag_ids")
    def _compute_dry_cleaning_garment_tag_count(self):
        for order in self:
            order.dry_cleaning_garment_tag_count = len(order.lines.garment_tag_ids)

    @api.constrains("state", "partner_id")
    def _check_dry_cleaning_customer_required(self):
        """A dry-cleaning order (any line with requires_garment_tag and a
        positive qty - the same qualifying condition frozen in Stage 2) must
        carry a customer once it has actually completed.

        This is the authoritative server-side gate: @api.constrains is
        checked on every flush regardless of entry path (POS UI, RPC, direct
        ORM write, import, a future integration), unlike a check placed only
        inside action_pos_order_paid(), which a direct
        write({'state': 'paid'}) elsewhere would bypass. Refund lines
        (negative qty) are excluded by the same qualifying condition, so
        refunds are never affected.
        """
        for order in self:
            if order.state not in ("paid", "done", "invoiced"):
                continue
            if order.partner_id:
                continue
            if order.lines.filtered(
                lambda l: l.product_id.requires_garment_tag and l.qty > 0
            ):
                raise ValidationError(_(
                    "A customer is required for orders containing a "
                    "dry-cleaning item."
                ))

    def action_pos_order_paid(self):
        result = super().action_pos_order_paid()
        self._dry_cleaning_process_order()
        return result

    def _dry_cleaning_process_order(self):
        """Ensure a ticket and a full set of garment tags exist for every
        dry-cleaning line on this now-paid order.

        Safe to call more than once against the same order: ticket lookup is
        get-or-create, and tag generation is idempotent per line (see
        pos.order.line._dry_cleaning_sync_garment_tags).
        """
        self.ensure_one()
        tag_lines = self.lines.filtered(
            lambda l: l.product_id.requires_garment_tag and l.qty > 0
        )
        if not tag_lines:
            return
        self.env["dry_cleaning.ticket"]._get_or_create_for_order(self)
        for line in tag_lines:
            line._dry_cleaning_sync_garment_tags()

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + [
            "dry_cleaning_ticket_name",
            "dry_cleaning_garment_tag_count",
        ]
