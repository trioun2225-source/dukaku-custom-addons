# -*- coding: utf-8 -*-
"""Stage 8B: read-only synchronization feed for the Dry Cleaning Operations
workspace.

This is deliberately NOT part of Stage 8A's mutation architecture (the
generic dukaku.offline.operation / handler registry) - it exists only so a
processing-area device can discover tickets/garments it did not itself
create or mutate (e.g. a ticket a POS terminal just produced, or a state
change made from another device or the backend). Stage 8A's endpoint
remains the only path for offline mutations; nothing here writes anything.

Deliberately dry-cleaning-scoped: this lives in dukaku_dry_cleaning, not in
dukaku_offline, so the dependency direction dukaku_dry_cleaning ->
dukaku_offline established in Stage 8/8A is never reversed and
dukaku_offline gains no knowledge of dry cleaning at all.

Closed response shape only - never a generic model/fields passthrough:
every field returned below is spelled out explicitly (mirrors the same
"closed dispatch, no arbitrary model/field access" posture Stage 8A's
handler registry already established), and no sudo() is used - the caller's
own environment is queried directly, so existing ir.model.access and the
multi-company ir.rule on dry_cleaning.ticket/garment_tag remain the sole
visibility authority, identical to what the backend views already show
that same user.
"""
import json

from odoo import api, fields, models


class DryCleaningTicketOpsSync(models.Model):
    _inherit = "dry_cleaning.ticket"

    @api.model
    def _ops_read_sync(self, cursor=None, limit=200):
        """Return tickets/garment tags changed since `cursor`, plus a new
        opaque cursor to resume from next time.

        `cursor` is treated as entirely opaque: it is only ever a string
        this method itself previously produced (see _ops_encode_cursor /
        _ops_decode_cursor below) - the client never constructs or
        interprets its contents, matching the same "opaque server-derived
        token" posture Stage 8A already uses for stream keys.

        Ordering/cursor key is write_date - a plain, already-existing field
        on every model, chosen specifically so this needs no new column on
        the frozen Stage 1-4 ticket/garment_tag models. `id` breaks ties
        for pagination ordering within one call only; see
        _ops_since_domain for why it is deliberately NOT part of the
        since-cursor filter itself. Not a general change-data-capture
        mechanism: no history/versioning is kept beyond "current row state
        as of last write", which is all an operational cache needs
        (Stage 8B review, sections 27-28).
        """
        self._ensure_authorized("process")
        limit = max(1, min(int(limit or 200), 200))

        cursor_state = self._ops_decode_cursor(cursor)
        ticket_domain = self._ops_since_domain(cursor_state.get("t"))
        garment_domain = self._ops_since_domain(cursor_state.get("g"))

        # active_test=False: an archived (POS-order-cancelled) ticket/tag
        # must still be reported so an already-cached copy on a device gets
        # told to drop it (§27 "cancellation/inactivation/removal
        # representable") - active is returned explicitly below for the
        # client to act on, never silently hidden by the default filter.
        Ticket = self.with_context(active_test=False)
        Garment = self.env["dry_cleaning.garment_tag"].with_context(active_test=False)

        tickets = Ticket.search(ticket_domain, order="write_date asc, id asc", limit=limit + 1)
        garments = Garment.search(garment_domain, order="write_date asc, id asc", limit=limit + 1)

        tickets_has_more = len(tickets) > limit
        garments_has_more = len(garments) > limit
        tickets = tickets[:limit]
        garments = garments[:limit]

        new_t_state = self._ops_cursor_point(tickets) or cursor_state.get("t")
        new_g_state = self._ops_cursor_point(garments) or cursor_state.get("g")

        return {
            "cursor": self._ops_encode_cursor(new_t_state, new_g_state),
            "has_more": bool(tickets_has_more or garments_has_more),
            "tickets": [self._ops_ticket_payload(t) for t in tickets],
            "garments": [self._ops_garment_payload(g) for g in garments],
        }

    def _ops_ticket_payload(self, ticket):
        """Closed, minimized field list - see the module docstring. No
        phone/email/address/payment/financial field is ever read or
        returned here (Stage 8B §26).
        """
        return {
            "ticket_id": ticket.id,
            "ticket_name": ticket.name,
            "state": ticket.state,
            "active": ticket.active,
            "company_id": ticket.company_id.id,
            "customer_name": ticket.partner_id.name or False,
            "server_write_date": fields.Datetime.to_string(ticket.write_date),
        }

    def _ops_garment_payload(self, garment):
        return {
            "garment_tag_id": garment.id,
            "ticket_id": garment.ticket_id.id,
            "barcode": garment.barcode,
            "product_name": garment.product_id.display_name or False,
            "intake_note": garment.intake_note or "",
            "active": garment.active,
            "server_write_date": fields.Datetime.to_string(garment.write_date),
        }

    @api.model
    def _ops_since_domain(self, point):
        """`point` is a write_date string (microsecond precision - see
        _ops_format_cursor_dt). Uses `>=` (inclusive), not `>`: Odoo sets
        write_date from Cursor.now(), which caches ONE timestamp for the
        entire transaction/request (see odoo/sql_db.py Cursor.now()) - two
        separate write() calls processed within the same transaction (e.g.
        two operations against the same ticket handled in one HTTP
        request, or two ORM writes in the same test) get the EXACT SAME
        write_date, down to the microsecond. An exclusive `>` plus an
        id-tiebreak cannot distinguish "already reported, unchanged" from
        "already reported, changed again in the same transaction" for the
        SAME row in that case - proven by an early test run against this
        exact method, not a hypothetical. `>=` trades a small, bounded
        cost (the single row at the previous cursor position may be
        harmlessly re-sent - the client already treats every row as an
        authoritative overwrite, so a redundant resend is a no-op) for
        the correctness property that actually matters here: a real
        change is never silently missed. No id-based exclusion is used at
        all, for the same reason.
        """
        if not point:
            return []
        return [("write_date", ">=", point)]

    @api.model
    def _ops_format_cursor_dt(self, dt):
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f") if dt else None

    @api.model
    def _ops_cursor_point(self, records):
        if not records:
            return None
        return self._ops_format_cursor_dt(records[-1].write_date)

    @api.model
    def _ops_encode_cursor(self, t_point, g_point):
        return json.dumps({"t": t_point, "g": g_point})

    @api.model
    def _ops_decode_cursor(self, cursor):
        if not cursor:
            return {}
        try:
            decoded = json.loads(cursor)
        except (TypeError, ValueError):
            return {}
        if not isinstance(decoded, dict):
            return {}
        return decoded
