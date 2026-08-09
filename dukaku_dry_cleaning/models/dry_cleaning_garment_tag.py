# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class DryCleaningGarmentTag(models.Model):
    """One physical garment produced by a dry-cleaning POS order line.

    A line with qty 3 yields three separate garment_tag records - there is no
    quantity field here by design (see Stage 2 scoping). pos_order_line_id is
    the only independently-set reference; pos_order_id and ticket_id are
    related/stored so the three references can never drift out of sync.
    """

    _name = "dry_cleaning.garment_tag"
    _description = "Dry Cleaning Garment Tag"
    _inherit = ["dry_cleaning.access.mixin"]
    _order = "id desc"

    # Stage 6 write-surface hardening: field-level readonly=True is a view
    # hint only and does not stop a direct write()/RPC call (verified
    # empirically - see Stage 6 audit). Every one of these sets is enforced
    # in write() below instead.
    #
    # related+store fields: writing one directly does NOT cascade through
    # the relation (Odoo only wires an inverse when the related field is
    # NOT readonly - these all are), but it DOES silently overwrite this
    # record's own stored column, diverging from the true related value -
    # e.g. company_id could be set to a value that no longer matches
    # pos_order_id.company_id, corrupting the very field the multi-company
    # record rule filters on. The internal recompute that keeps these in
    # sync writes through the field cache directly (never calls this
    # model's write()), so it is unaffected by the guard.
    _DERIVED_FIELDS = frozenset({"pos_order_id", "ticket_id", "product_id", "company_id"})
    # Set once at create() time (pos_order_line_id via vals, barcode/name
    # via create()'s own defaulting) and never legitimately changed after -
    # rewriting any of these after issuance is a garment-identity/fraud
    # vector (a relabeled or reassigned tag could be scanned as if it were
    # a different physical garment).
    _IMMUTABLE_AFTER_CREATE = frozenset({"pos_order_line_id", "barcode", "name"})
    # Only ever legitimately set by action_print_garment_tags(), which
    # bypasses this guard via super().write() - the same bypass pattern
    # dry_cleaning.ticket uses for 'state'.
    _PRINT_BOOKKEEPING_FIELDS = frozenset({"printed", "printed_date"})

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
    ticket_state = fields.Selection(
        related="ticket_id.state", readonly=True,
        help="Stage 6 UI convenience field: lets the form gray out "
             "intake_note once the ticket has left its editable window, "
             "without duplicating the ticket's state selection here. Not "
             "the enforcement mechanism - write() enforces the same "
             "lifecycle rule server-side regardless of this field.",
    )
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
                "pos_order_id, ticket_id, product_id, and company_id are "
                "derived from pos_order_line_id and cannot be set directly."
            ))
        if self._IMMUTABLE_AFTER_CREATE.intersection(vals):
            raise UserError(_(
                "This garment tag's identity (pos_order_line_id, barcode, "
                "or name) cannot be changed after creation."
            ))
        if self._PRINT_BOOKKEEPING_FIELDS.intersection(vals):
            raise UserError(_(
                "printed and printed_date cannot be written directly. "
                "Use action_print_garment_tags() instead."
            ))
        if "active" in vals:
            raise UserError(_(
                "active cannot be written directly on a garment tag."
            ))
        if "intake_note" in vals:
            # The single enforcement point for intake_note, reached by any
            # caller - the inline editable list on the ticket form,
            # action_update_intake_note() below, or a direct RPC write -
            # since all of them ultimately call this write(). There is no
            # separate code path that could set intake_note without going
            # through these two checks.
            self._check_intake_note_authorized()
            self._check_intake_note_editable()
        return super().write(vals)

    def _check_intake_note_authorized(self):
        """Cashier (base User), Processor (Can Process), and Manager may
        edit intake notes. A user whose only dry-cleaning capability is
        Can Pickup may not - pickup-only staff have no operational reason
        to touch intake data (Stage 5 review, Section 9). Someone holding
        both Can Process and Can Pickup - the single-employee small-shop
        case - is unaffected: the Can Process capability alone authorizes
        this, checked first below.
        """
        user = self.env.user
        if user.has_group(self._MANAGER_GROUP):
            return
        if user.has_group(self._CAPABILITY_GROUPS["process"]):
            return
        if user.has_group(self._CAPABILITY_GROUPS["pickup"]):
            raise AccessError(_(
                "Pickup staff cannot edit intake notes."
            ))
        # Base Dry Cleaning User with no capability group (plain cashier).

    def _check_intake_note_editable(self):
        """Intake notes are only editable while the ticket is still in its
        intake/processing window. Locked for everyone, including Manager,
        once the ticket reaches 'ready' - this is data describing what
        happened at intake, and rewriting it after the ticket is
        functionally closed is exactly what the immutable event log
        elsewhere in this module exists to prevent (Stage 5 review,
        Section 6).
        """
        for tag in self:
            if tag.ticket_id.state not in ("drop_off", "in_progress"):
                raise UserError(_(
                    "The intake note for garment tag %(tag)s can no longer "
                    "be edited: its ticket is already '%(state)s'.",
                    tag=tag.name,
                    state=tag.ticket_id.state,
                ))

    def action_update_intake_note(self, note):
        """Controlled entry point for editing intake_note. Delegates
        entirely to write() above rather than duplicating its checks, so
        this method and a direct write({'intake_note': ...}) are always
        subject to exactly the same authorization and lifecycle rules.
        """
        self.ensure_one()
        return self.write({"intake_note": note})

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

        Initial printing (printed=False) is open to any Dry Cleaning User;
        reprinting an already-printed tag requires the Can Reprint
        capability (or Manager). The check runs against self.filtered
        ("printed") - only the subset already printed - so a mixed batch
        (some fresh, some already printed) can never let an unauthorized
        user reprint just because one tag in the selection is unprinted:
        if any tag in self is already printed, the whole call requires the
        capability, checked before anything is written.
        """
        if self.filtered("printed"):
            self._ensure_authorized("reprint")
        # super().write() deliberately bypasses this class's own write()
        # guard above (which rejects direct printed/printed_date writes) -
        # this method, reached only after the authorization check just
        # above, is the sole legitimate path to change print bookkeeping.
        # Same bypass pattern as dry_cleaning.ticket._transition_to()
        # bypassing its own 'state' guard.
        super(DryCleaningGarmentTag, self).write({
            "printed": True,
            "printed_date": fields.Datetime.now(),
        })
        return self.env.ref(
            "dukaku_dry_cleaning.action_report_dry_cleaning_garment_tag_label"
        ).report_action(self)
