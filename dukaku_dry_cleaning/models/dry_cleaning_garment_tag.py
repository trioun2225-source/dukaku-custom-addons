# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class DryCleaningGarmentTag(models.Model):
    """One physical garment produced by a dry-cleaning POS order line.

    A line with qty 3 yields three separate garment_tag records - there is no
    quantity field here by design (see Stage 2 scoping). pos_order_line_id is
    the only independently-set reference; pos_order_id and ticket_id are
    related/stored so the three references can never drift out of sync.
    """

    _name = "dry_cleaning.garment_tag"
    _description = "Dry Cleaning Garment Tag"
    _order = "id desc"

    # related+store+readonly already stops these from showing up as editable
    # in views; write() additionally hard-blocks them from any direct RPC/
    # server-side call, so pos_order_line_id is genuinely the only way to
    # establish the relationship (the internal recompute that keeps these
    # fields in sync writes through the field cache directly and never goes
    # through this method, so it is unaffected by the guard).
    _DERIVED_FIELDS = frozenset({"pos_order_id", "ticket_id"})

    name = fields.Char(
        string="Tag Number",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        help="Human-readable tag number. Always equal to the barcode value.",
    )
    barcode = fields.Char(
        required=True,
        copy=False,
        readonly=True,
        help="Code128 barcode value, unique within this database. Matches the tag number.",
    )
    pos_order_line_id = fields.Many2one(
        "pos.order.line",
        string="POS Order Line",
        required=True,
        ondelete="cascade",
        index=True,
    )
    pos_order_id = fields.Many2one(
        "pos.order",
        string="POS Order",
        related="pos_order_line_id.order_id",
        store=True,
        readonly=True,
        index=True,
    )
    ticket_id = fields.Many2one(
        "dry_cleaning.ticket",
        string="Dry Cleaning Ticket",
        related="pos_order_line_id.order_id.dry_cleaning_ticket_id",
        store=True,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        related="pos_order_id.company_id", store=True, readonly=True, index=True
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        related="pos_order_line_id.product_id",
        store=True,
        readonly=True,
        help="Stage 4 UI convenience field (ticket form, barcode lookup) - "
             "readonly like the other related fields above, so it can never "
             "be used to redirect this tag's write-through to a different "
             "order line's product.",
    )
    intake_note = fields.Text()
    printed = fields.Boolean(default=False, copy=False)
    printed_date = fields.Datetime(readonly=True, copy=False)
    active = fields.Boolean(compute="_compute_active", store=True)

    _barcode_uniq = models.Constraint(
        "unique(barcode)",
        "This barcode is already assigned to another garment tag.",
    )
    _name_uniq = models.Constraint(
        "unique(name)",
        "This tag number is already assigned to another garment tag.",
    )

    @api.depends("pos_order_id.state")
    def _compute_active(self):
        """Archive the tag automatically when its POS order is cancelled.

        Mirrors dry_cleaning.ticket._compute_active so a garment tag and its
        ticket always agree on whether they're archived.
        """
        for tag in self:
            tag.active = tag.pos_order_id.state != "cancel"

    def _generate_barcode(self):
        """Return a fresh Code128 value, unique within this tenant's database.

        Mirrors the collision-check convention used by dukaku_barcode's
        product barcode generation, scoped to this model instead of
        product.template - the two live in independent uniqueness domains
        (a product barcode and a garment tag barcode are never compared
        against each other), so the check is against this model only.
        """
        for _attempt in range(100):
            barcode = self.env["ir.sequence"].next_by_code("dry_cleaning.garment_tag")
            if not barcode:
                raise ValidationError(_(
                    "Garment tag sequence not found. Try reinstalling dukaku_dry_cleaning."
                ))
            if not self.search([("barcode", "=", barcode)], limit=1):
                return barcode
        raise ValidationError(_(
            "Could not generate a unique garment tag barcode after 100 attempts."
        ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("barcode"):
                vals["barcode"] = self._generate_barcode()
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = vals["barcode"]
        return super().create(vals_list)

    def write(self, vals):
        if self._DERIVED_FIELDS.intersection(vals):
            raise UserError(_(
                "pos_order_id and ticket_id are derived from pos_order_line_id "
                "and cannot be set directly."
            ))
        return super().write(vals)

    @api.model
    def lookup_by_barcode(self, barcode):
        """Resolve a scanned barcode to everything an operator needs in one call.

        Returns False if no tag matches, so a scan of an unknown/foreign
        barcode can be handled without a second lookup.
        """
        tag = self.search([("barcode", "=", barcode)], limit=1)
        if not tag:
            return False
        order = tag.pos_order_id
        ticket = tag.ticket_id
        return {
            "garment_tag_id": tag.id,
            "tag_number": tag.name,
            "intake_note": tag.intake_note,
            "ticket_id": ticket.id,
            "ticket_name": ticket.name,
            "ticket_state": ticket.state,
            "pos_order_id": order.id,
            "pos_order_name": order.name,
            "customer_id": order.partner_id.id,
            "customer_name": order.partner_id.name,
        }

    def _barcode_svg_uri(self):
        """Inline SVG data URI for this tag's Code128 barcode.

        Mirrors product.template._barcode_svg_uri in dukaku_barcode (same
        renderSVG approach - no rlPyCairo/renderPM dependency), simplified
        since garment tags are always Code128, never EAN-13.
        """
        from reportlab.graphics.barcode import createBarcodeDrawing
        from reportlab.graphics import renderSVG
        import base64

        self.ensure_one()
        drawing = createBarcodeDrawing(
            "Code128", value=self.barcode,
            width=420, height=150, humanReadable=True,
        )
        svg_str = renderSVG.drawToString(drawing)
        return "data:image/svg+xml;base64," + base64.b64encode(
            svg_str.encode("utf-8")).decode("ascii")

    def action_print_garment_tags(self):
        """Print (or reprint) the thermal label for every tag in self.

        Single-record and batch calls both go through this method, so
        printed/printed_date always reflect the most recent print regardless
        of how many tags were selected. This is the same entry point for a
        first print and a reprint - there is no separate "reprint" action.
        """
        self.write({
            "printed": True,
            "printed_date": fields.Datetime.now(),
        })
        return self.env.ref(
            "dukaku_dry_cleaning.action_report_dry_cleaning_garment_tag_label"
        ).report_action(self)
