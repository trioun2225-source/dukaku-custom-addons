# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class DryCleaningBarcodeLookup(models.TransientModel):
    """Simple backend operational interface for scanning a garment barcode.

    Reuses dry_cleaning.garment_tag.lookup_by_barcode() (Stage 2, frozen) as
    the sole lookup mechanism - exact match only, no fuzzy matching, never
    creates a garment tag from an unrecognized scan. Any standard keyboard-
    wedge barcode scanner works here: it just types the barcode into the
    field below and sends a trailing Enter/Tab, which triggers the onchange
    like any normal keyboard input - no special hardware integration needed.
    """

    _name = "dry_cleaning.barcode_lookup"
    _description = "Dry Cleaning Barcode Lookup"

    barcode = fields.Char(string="Scan Barcode")
    scanned_barcode = fields.Char(readonly=True, string="Last Scanned")
    not_found = fields.Boolean(readonly=True, default=False)

    garment_tag_id = fields.Many2one(
        "dry_cleaning.garment_tag", readonly=True, string="Garment"
    )
    ticket_id = fields.Many2one(
        related="garment_tag_id.ticket_id", readonly=True
    )
    ticket_state = fields.Selection(
        related="garment_tag_id.ticket_id.state", readonly=True
    )
    partner_id = fields.Many2one(
        related="garment_tag_id.ticket_id.partner_id", readonly=True, string="Customer"
    )
    pos_order_id = fields.Many2one(
        related="garment_tag_id.pos_order_id", readonly=True
    )
    intake_note = fields.Text(related="garment_tag_id.intake_note", readonly=True)
    sibling_garment_tag_ids = fields.Many2many(
        "dry_cleaning.garment_tag",
        compute="_compute_sibling_garment_tag_ids",
        string="All Garments on This Ticket",
    )

    @api.depends("garment_tag_id")
    def _compute_sibling_garment_tag_ids(self):
        for wizard in self:
            wizard.sibling_garment_tag_ids = wizard.garment_tag_id.ticket_id.garment_tag_ids

    @api.onchange("barcode")
    def _onchange_barcode(self):
        if not self.barcode:
            return
        info = self.env["dry_cleaning.garment_tag"].lookup_by_barcode(self.barcode)
        self.scanned_barcode = self.barcode
        # Clear the input immediately so the next scan can be typed/read
        # right away without the operator manually clearing the field.
        self.barcode = False
        if not info:
            self.garment_tag_id = False
            self.not_found = True
        else:
            self.garment_tag_id = info["garment_tag_id"]
            self.not_found = False

    def _reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_ticket_start(self):
        self.ticket_id.action_start()
        return self._reopen()

    def action_ticket_mark_ready(self):
        self.ticket_id.action_mark_ready()
        return self._reopen()

    def action_ticket_pick_up(self):
        self.ticket_id.action_pick_up()
        return self._reopen()

    def action_open_ticket(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "dry_cleaning.ticket",
            "res_id": self.ticket_id.id,
            "view_mode": "form",
            "target": "current",
        }
