# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class InvalidTicketTransitionError(UserError):
    """Raised specifically by _check_transition() when a requested
    transition doesn't follow the ticket's current state - the one
    condition _ui_wrap_transition() below is meant to recognize and turn
    into a friendly "already updated" notification.

    A plain UserError subclass with no behavior of its own: it changes
    nothing about what _check_transition validates, when it raises, or what
    message it raises with - only the exception class used to signal that
    one specific, already-existing outcome. This exists so callers can
    distinguish it via isinstance() rather than parsing translated message
    text, so any *other* UserError a future change might introduce into
    this call chain keeps propagating normally instead of being
    misrepresented as a stale transition.
    """


class DryCleaningTicket(models.Model):
    """Operational tracking ticket for a garment drop-off, linked 1:1 to a POS order.

    The ticket never carries pricing or order-line data — that stays on
    pos.order / pos.order.line. It only tracks the physical garment
    workflow: drop_off -> in_progress -> ready -> picked_up.
    """

    _name = "dry_cleaning.ticket"
    _description = "Dry Cleaning Ticket"
    _inherit = ["mail.thread"]
    _order = "id desc"

    # Forward-only workflow; each state may only advance to the next one.
    _STATE_SEQUENCE = ["drop_off", "in_progress", "ready", "picked_up"]

    name = fields.Char(
        required=True, copy=False, readonly=True, default=lambda self: _("New")
    )
    pos_order_id = fields.Many2one(
        "pos.order",
        string="POS Order",
        required=True,
        ondelete="cascade",
        copy=False,
    )
    company_id = fields.Many2one(
        related="pos_order_id.company_id", store=True, index=True, readonly=True
    )
    state = fields.Selection(
        [
            ("drop_off", "Drop-off"),
            ("in_progress", "In Progress"),
            ("ready", "Ready"),
            ("picked_up", "Picked Up"),
        ],
        default="drop_off",
        required=True,
        copy=False,
        tracking=True,
        index=True,
    )
    active = fields.Boolean(compute="_compute_active", store=True)

    # -- Stage 4: read-only convenience fields for the operational UI. Purely
    # additive - no frozen Stage 1-3 field, constraint or method is touched.
    partner_id = fields.Many2one(
        "res.partner", string="Customer",
        related="pos_order_id.partner_id", store=True, index=True, readonly=True,
    )
    garment_tag_ids = fields.One2many(
        "dry_cleaning.garment_tag", "ticket_id", string="Garment Tags"
    )
    garment_tag_count = fields.Integer(
        compute="_compute_garment_tag_count", string="Garments"
    )
    event_ids = fields.One2many(
        "dry_cleaning.event", "ticket_id", string="Events",
        help="Read-only operational history. dry_cleaning.event enforces its "
             "own immutability (write/unlink always raise), so this relation "
             "cannot be used to edit history regardless of view configuration.",
    )
    last_event_id = fields.Many2one(
        "dry_cleaning.event", compute="_compute_last_event_id",
        string="Last Activity",
    )
    last_event_at = fields.Datetime(
        compute="_compute_last_event_id", string="Last Activity At"
    )

    _pos_order_uniq = models.Constraint(
        "unique(pos_order_id)",
        "A POS order can only have one dry cleaning ticket.",
    )

    @api.depends("pos_order_id.state")
    def _compute_active(self):
        """Archive the ticket automatically when its POS order is cancelled.

        No new workflow state is introduced for cancellation: the ticket
        keeps whatever state it was in and simply drops out of active views.
        """
        for ticket in self:
            ticket.active = ticket.pos_order_id.state != "cancel"

    @api.depends("garment_tag_ids")
    def _compute_garment_tag_count(self):
        for ticket in self:
            ticket.garment_tag_count = len(ticket.garment_tag_ids)

    @api.depends("event_ids")
    def _compute_last_event_id(self):
        for ticket in self:
            # event_ids follows dry_cleaning.event's frozen
            # _order = "event_at asc, id asc", so the last item is the
            # most recent event.
            last_event = ticket.event_ids[-1:]
            ticket.last_event_id = last_event
            ticket.last_event_at = last_event.event_at

    def write(self, vals):
        """Reject direct writes to 'state' from outside this class.

        _transition_to() is the only legitimate path for a state change; it
        bypasses this check entirely by calling super(DryCleaningTicket,
        self).write() directly rather than going through this method, so it
        is unaffected by the guard below. Every other field remains
        writable as normal.
        """
        if "state" in vals:
            raise UserError(_(
                "dry_cleaning.ticket.state cannot be written directly. "
                "Use action_start / action_mark_ready / action_pick_up instead."
            ))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("dry_cleaning.ticket")
                    or _("New")
                )
        tickets = super().create(vals_list)
        # Every genuinely new ticket gets its initial drop_off event here, in
        # the same method/transaction as the ticket row itself - never as a
        # separate follow-up call - so a ticket can never end up with zero
        # events even if action_pos_order_paid fires more than once.
        # sudo() is required since no group has create access on
        # dry_cleaning.event directly; self.env.user is unaffected by sudo()
        # so user_id still captures the real actor, not the superuser.
        self.env["dry_cleaning.event"].sudo().create([
            {"ticket_id": ticket.id, "event_type": "drop_off"}
            for ticket in tickets
        ])
        return tickets

    @api.model
    def _get_or_create_for_order(self, pos_order):
        """Return the ticket for pos_order, creating one if none exists yet.

        Reuses create() as-is (sequence naming), so ticket-creation logic
        stays in one place.
        """
        ticket = self.search([("pos_order_id", "=", pos_order.id)], limit=1)
        if not ticket:
            ticket = self.create({"pos_order_id": pos_order.id})
        return ticket

    def _check_transition(self, target_state):
        """Ensure every ticket in self is exactly one step before target_state."""
        target_index = self._STATE_SEQUENCE.index(target_state)
        for ticket in self:
            current_index = self._STATE_SEQUENCE.index(ticket.state)
            if current_index != target_index - 1:
                raise InvalidTicketTransitionError(_(
                    "Ticket %(name)s cannot move from '%(current)s' directly to "
                    "'%(target)s'.",
                    name=ticket.name,
                    current=ticket.state,
                    target=target_state,
                ))

    def _transition_to(self, new_state, source="server", note=None):
        """Move every ticket in self to new_state and log one matching event
        each, as a single pair per ticket sharing this method's transaction.

        The only place a workflow state change is allowed to happen -
        action_start/action_mark_ready/action_pick_up are thin wrappers
        around this, so state and event can never drift apart.

        Writes 'state' via super().write(), bypassing this class's own
        write() override below (which rejects direct 'state' writes) without
        skipping the rest of the MRO (mail.thread tracking still fires
        normally). Event creation needs sudo() since no group has create
        access on dry_cleaning.event directly; sudo() doesn't touch
        self.env.user, so user_id below still captures the real actor.
        """
        self._check_transition(new_state)
        super(DryCleaningTicket, self).write({"state": new_state})
        self.env["dry_cleaning.event"].sudo().create([
            {
                "ticket_id": ticket.id,
                "event_type": new_state,
                "source": source,
                "note": note,
            }
            for ticket in self
        ])

    def action_start(self):
        """Transition drop_off -> in_progress."""
        self._transition_to("in_progress")

    def action_mark_ready(self):
        """Transition in_progress -> ready."""
        self._transition_to("ready")

    def action_pick_up(self):
        """Transition ready -> picked_up."""
        self._transition_to("picked_up")

    def _ui_wrap_transition(self, method_name):
        """Call one of the three action_* methods above unchanged, and turn a
        rejected (stale) transition into a clear, non-raising result instead
        of a generic error dialog.

        This does not validate or duplicate anything _check_transition /
        _transition_to already do - it only calls that existing, untouched
        method and reacts to what it raises. Only InvalidTicketTransitionError
        (the dedicated, narrowly-scoped exception _check_transition raises)
        is treated as "already updated" - any other UserError this call
        chain might someday raise propagates normally, uncaught here. The
        only reason this exists: Odoo's standard type="object" button only
        reloads the record's displayed fields (and re-evaluates each
        button's invisible=...) on the *success* path, via the
        ir.actions.act_window_close it gets back - a raised UserError skips
        that reload entirely, leaving the form showing the stale state and
        a now-obsolete action button. Returning a non-raising
        display_notification action with next=act_window_close drives the
        exact same standard reload path a successful click uses, without
        adding any new client-side transition logic - the frontend does
        nothing here it doesn't already know how to do.
        """
        self.ensure_one()
        try:
            getattr(self, method_name)()
        except InvalidTicketTransitionError:
            # _description_selection() is the translation-aware accessor
            # (respects self.env's language) - self._fields["state"].selection
            # would return the raw, untranslated Python-source labels.
            state_label = dict(
                self._fields["state"]._description_selection(self.env)
            ).get(self.state, self.state)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Ticket Already Updated"),
                    "message": _(
                        "This ticket was already updated. Current status: %(state)s.",
                        state=state_label,
                    ),
                    "type": "warning",
                    "sticky": True,
                },
                "next": {"type": "ir.actions.act_window_close"},
            }
        return {"type": "ir.actions.act_window_close"}

    def action_start_ui(self):
        """UI entry point for the ticket form's "Start Processing" button."""
        return self._ui_wrap_transition("action_start")

    def action_mark_ready_ui(self):
        """UI entry point for the ticket form's "Mark Ready" button."""
        return self._ui_wrap_transition("action_mark_ready")

    def action_pick_up_ui(self):
        """UI entry point for the ticket form's "Confirm Pickup" button."""
        return self._ui_wrap_transition("action_pick_up")

    def action_print_garment_tags(self):
        """Print (or reprint) every garment tag belonging to this ticket.

        Stage 4 convenience wrapper only: reuses
        dry_cleaning.garment_tag.action_print_garment_tags() as-is (Stage 2,
        frozen) for the actual report action and printed/printed_date
        bookkeeping - no printing logic is duplicated here, and no
        dry_cleaning.event is created (printing is not a workflow event).
        """
        self.ensure_one()
        return self.garment_tag_ids.action_print_garment_tags()
