# -*- coding: utf-8 -*-
"""Stage 8/8A: dry-cleaning registrations against dukaku_offline's
database-registry-aware handler registry.

Extends dukaku.offline.handler.registry via normal Odoo _inherit - not a
process-global side effect. A database without dukaku_dry_cleaning
installed simply never has this class in its registry's MRO, so its
handlers cannot appear there regardless of what any other database in the
same Python worker process has loaded (Stage 8A §1).

Only three operation types are registered - exactly the frozen offline-
supported set. Confirm Pickup, printing, and reprinting have no handler at
all: an offline submission naming any of them resolves to
UNKNOWN_OPERATION in the generic dispatcher, with nothing dry-cleaning-
specific needed to enforce that.

Each handler is a thin wrapper: resolve the target record under the
caller's own (never sudo'd) environment, call the existing frozen business
method, translate whatever it raises into OfflineOperationRejected with a
reason_code this module chooses (dukaku_offline has no vertical knowledge
to classify a rejection itself). For the two conflict classes where the
target was legitimately resolved and visible (STALE_STATE,
LIFECYCLE_LOCKED), a minimal, non-sensitive snapshot is attached so the
client can reconcile its cache - never for an access-denied class.
"""
from odoo import models
from odoo.exceptions import AccessError, UserError

from odoo.addons.dukaku_offline.models.offline_operation import OfflineOperationRejected

from .dry_cleaning_ticket import InvalidTicketTransitionError


def _ticket_snapshot(ticket):
    return {
        "ticket_id": ticket.id,
        "ticket_name": ticket.name,
        "state": ticket.state,
        "company_id": ticket.company_id.id,
    }


class DryCleaningOfflineHandlerRegistry(models.AbstractModel):
    _inherit = "dukaku.offline.handler.registry"

    def _get_offline_handlers(self):
        handlers = super()._get_offline_handlers()
        handlers.update({
            "dry_cleaning.start_processing": self._offline_start_processing,
            "dry_cleaning.mark_ready": self._offline_mark_ready,
            "dry_cleaning.update_intake_note": self._offline_update_intake_note,
        })
        return handlers

    def _get_offline_stream_key(self, env, operation_type, payload):
        """Both ticket-transition operations key directly off ticket_id.
        The note-update operation targets a garment tag but belongs to the
        same workflow stream as its ticket, so a failed transition on that
        ticket also blocks a queued note edit against one of its tags -
        resolved via a plain, cheap read under the CALLER'S OWN env (no
        sudo - a tag this user cannot access must not derive a stream key
        either), never raising: an unresolvable or inaccessible target
        here just means "no stream" (the handler itself raises
        TARGET_NOT_FOUND/NOT_AUTHORIZED when actually dispatched).
        """
        if operation_type in ("dry_cleaning.start_processing", "dry_cleaning.mark_ready"):
            ticket_id = payload.get("ticket_id")
            if ticket_id:
                return f"dry_cleaning.ticket:{int(ticket_id)}"
            return None
        if operation_type == "dry_cleaning.update_intake_note":
            tag_id = payload.get("garment_tag_id")
            if not tag_id:
                return None
            try:
                tag = env["dry_cleaning.garment_tag"].browse(int(tag_id))
                if not tag.exists() or not tag.ticket_id:
                    return None
                return f"dry_cleaning.ticket:{tag.ticket_id.id}"
            except AccessError:
                return None
        return super()._get_offline_stream_key(env, operation_type, payload)

    def _resolve_ticket(self, env, payload):
        ticket_id = payload.get("ticket_id")
        if not ticket_id:
            raise OfflineOperationRejected("VALIDATION_ERROR", "ticket_id is required.")
        ticket = env["dry_cleaning.ticket"].browse(int(ticket_id))
        if not ticket.exists():
            raise OfflineOperationRejected("TARGET_NOT_FOUND", "Ticket not found.")
        return ticket

    def _offline_start_processing(self, env, payload):
        ticket = self._resolve_ticket(env, payload)
        try:
            ticket.action_start()
        except AccessError as exc:
            raise OfflineOperationRejected("NOT_AUTHORIZED", str(exc)) from exc
        except InvalidTicketTransitionError as exc:
            raise OfflineOperationRejected(
                "STALE_STATE", str(exc), snapshot=_ticket_snapshot(ticket)
            ) from exc
        except UserError as exc:
            raise OfflineOperationRejected("VALIDATION_ERROR", str(exc)) from exc
        return _ticket_snapshot(ticket)

    def _offline_mark_ready(self, env, payload):
        ticket = self._resolve_ticket(env, payload)
        try:
            ticket.action_mark_ready()
        except AccessError as exc:
            raise OfflineOperationRejected("NOT_AUTHORIZED", str(exc)) from exc
        except InvalidTicketTransitionError as exc:
            raise OfflineOperationRejected(
                "STALE_STATE", str(exc), snapshot=_ticket_snapshot(ticket)
            ) from exc
        except UserError as exc:
            raise OfflineOperationRejected("VALIDATION_ERROR", str(exc)) from exc
        return _ticket_snapshot(ticket)

    def _offline_update_intake_note(self, env, payload):
        tag_id = payload.get("garment_tag_id")
        if not tag_id:
            raise OfflineOperationRejected("VALIDATION_ERROR", "garment_tag_id is required.")
        tag = env["dry_cleaning.garment_tag"].browse(int(tag_id))
        if not tag.exists():
            raise OfflineOperationRejected("TARGET_NOT_FOUND", "Garment tag not found.")
        note = payload.get("note") or ""
        try:
            tag.action_update_intake_note(note)
        except AccessError as exc:
            raise OfflineOperationRejected("NOT_AUTHORIZED", str(exc)) from exc
        except UserError as exc:
            # _check_intake_note_editable's lifecycle-lock UserError lands
            # here - the generic layer has no notion of "lifecycle", so
            # this module chooses LIFECYCLE_LOCKED itself, and the ticket
            # was legitimately resolved/visible, so a snapshot is safe.
            raise OfflineOperationRejected(
                "LIFECYCLE_LOCKED", str(exc),
                snapshot={
                    "ticket_id": tag.ticket_id.id,
                    "ticket_name": tag.ticket_id.name,
                    "state": tag.ticket_id.state,
                    "company_id": tag.company_id.id,
                },
            ) from exc
        return {
            "garment_tag_id": tag.id,
            "intake_note": tag.intake_note,
            "ticket_id": tag.ticket_id.id,
            "ticket_state": tag.ticket_id.state,
        }
