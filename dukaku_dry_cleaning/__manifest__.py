# -*- coding: utf-8 -*-
{
    "name": "Dukaku Dry Cleaning",
    "version": "19.0.5.0.0",
    "category": "Point of Sale",
    "summary": "Garment ticket tracking and tag/barcode system for the Dukaku Point of Sale",
    "description": """
Dukaku Dry Cleaning
====================
Extends the Dukaku Point of Sale with garment ticket tracking for dry
cleaning drop-offs. This module is an extension of the existing POS flow,
not a standalone application: it does not modify pos.order, pos.order.line,
or the payment lifecycle, and it carries no pricing or catalog data of its
own.

Each paid POS order may be linked to one dry cleaning ticket, tracking the
physical garment through drop_off -> in_progress -> ready -> picked_up.

Stage 2 adds garment tags: when a paid order line's product is flagged
requires_garment_tag, one uniquely barcoded dry_cleaning.garment_tag record
is generated per unit of quantity, linked back to its order line, order and
ticket.

Stage 3 adds an immutable dry_cleaning.event audit log: every ticket state
change (starting with its initial drop_off) is recorded as its own event,
written only through dry_cleaning.ticket's centralized _transition_to()
service, never editable or deletable afterwards.

Stage 4 adds the operational UI and POS integration: backend ticket list/
form views with workflow buttons, a barcode lookup wizard, batch/reprint
garment-label printing, a mandatory-customer check for qualifying orders
(server-authoritative, POS-side UX only), and minimal POS additions - a
post-payment "print garment labels" action and a small receipt block -
built entirely on Odoo's standard POS data-loading and report-download
mechanisms. No second checkout, no new order/payment/tax model.

Stage 8 registers three offline-queueable operations (Start Processing, Mark
Ready, intake-note update) against dukaku_offline's generic, vertical-agnostic
synchronization registry - each a thin wrapper around the existing frozen
business method, so authorization, transition validity, and event creation
are never duplicated. Confirm Pickup, printing, and reprinting remain
online-only by having no registered handler at all.

This module is an addon within the broader Dukaku ecosystem and depends on
Odoo's core Point of Sale app, on dukaku_barcode for its thermal label
paperformat, and on dukaku_offline for offline-operation synchronization.
""",
    "author": "Dukaku",
    "website": "https://www.dukaku.com",
    "license": "OPL-1",
    "depends": [
        "base",
        "point_of_sale",
        "mail",
        "dukaku_barcode",
        "dukaku_offline",
    ],
    "data": [
        "security/dry_cleaning_security.xml",
        "security/ir.model.access.csv",
        "data/dry_cleaning_ticket_sequence.xml",
        "data/garment_tag_sequence.xml",
        "views/product_views.xml",
        "views/dry_cleaning_garment_tag_views.xml",
        "views/dry_cleaning_event_views.xml",
        "views/dry_cleaning_ticket_views.xml",
        "views/dry_cleaning_barcode_lookup_views.xml",
        "report/dry_cleaning_garment_tag_label.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "dukaku_dry_cleaning/static/src/app/utils/dry_cleaning_order_validation.js",
            "dukaku_dry_cleaning/static/src/app/screens/receipt_screen/receipt_screen.js",
            "dukaku_dry_cleaning/static/src/app/screens/receipt_screen/receipt_screen.xml",
            "dukaku_dry_cleaning/static/src/app/screens/receipt_screen/receipt/dukaku_dry_cleaning_order_receipt.xml",
        ],
    },
    "demo": [],
    "installable": True,
    "application": False,
    "auto_install": False,
}
