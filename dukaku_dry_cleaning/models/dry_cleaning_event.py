# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class DryCleaningEvent(models.Model):
    """Immutable audit-log entry for a dry cleaning ticket's workflow.

    Append-only by design: write() and unlink() always raise, regardless of
    group or sudo() context (see write()/unlink() below), so this is the
    tamper-resistant history the ticket.state column alone can't provide.
    Events are never created directly by user action - only through
    dry_cleaning.ticket.create() (the initial drop_off) and
    dry_cleaning.ticket._transition_to() (every subsequent state change).
    """

    _name = "dry_cleaning.event"
    _description = "Dry Cleaning Ticket Event"
    _order = "event_at asc, id asc"

    ticket_id = fields.Many2one(
        "dry_cleaning.ticket",
        required=True,
        ondelete="restrict",
    )
    garment_tag_id = fields.Many2one(
        "dry_cleaning.garment_tag",
        ondelete="restrict",
    )
    event_type = fields.Selection(
        [
            ("drop_off", "Drop-off"),
            ("in_progress", "In Progress"),
            ("ready", "Ready"),
            ("picked_up", "Picked Up"),
        ],
        required=True,
    )
    event_at = fields.Datetime(required=True, default=fields.Datetime.now)
    user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user
    )
    company_id = fields.Many2one(
        related="ticket_id.company_id", store=True, index=True, readonly=True
    )
    source = fields.Selection(
        [
            ("server", "Server"),
            ("pos", "Point of Sale"),
        ],
        required=True,
        default="server",
    )
    note = fields.Text()

    _ticket_id_event_at_idx = models.Index("(ticket_id, event_at)")

    @api.constrains("ticket_id", "garment_tag_id")
    def _check_garment_tag_ticket_consistency(self):
        for event in self:
            if event.garment_tag_id and event.garment_tag_id.ticket_id != event.ticket_id:
                raise ValidationError(_(
                    "This event's garment tag (%(tag)s) belongs to ticket "
                    "%(tag_ticket)s, not %(event_ticket)s.",
                    tag=event.garment_tag_id.name,
                    tag_ticket=event.garment_tag_id.ticket_id.name,
                    event_ticket=event.ticket_id.name,
                ))

    def write(self, vals):
        raise UserError(_("Dry cleaning events are an immutable audit log and cannot be modified."))

    def unlink(self):
        raise UserError(_("Dry cleaning events are an immutable audit log and cannot be deleted."))
