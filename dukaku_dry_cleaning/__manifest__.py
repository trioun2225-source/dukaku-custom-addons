# -*- coding: utf-8 -*-
{
    "name": "Dukaku Dry Cleaning POS",
    "version": "19.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Dry cleaning management and POS integration for the Dukaku ecosystem",
    "description": """
Dukaku Dry Cleaning POS
========================
Commercial-grade dry cleaning management module for the Dukaku POS ecosystem.

Features (delivered incrementally):
* Dry cleaning order management (garments, services, pricing, status workflow)
* Customer preference tracking
* Barcode / QR code order tracking
* POS integration (orders, payments, receipts)
* Multi-company / multi-branch ready
* Thermal receipt and order ticket printing

This module is an addon within the broader Dukaku ecosystem and depends on
Odoo's core Point of Sale, Contacts, and Inventory apps.
""",
    "author": "Dukaku",
    "website": "https://www.dukaku.com",
    "license": "OPL-1",
    "depends": [
        "base",
        "point_of_sale",
        "contacts",
        "mail",
    ],
    "data": [
        "security/dry_cleaning_security.xml",
        "security/dry_cleaning_order_rules.xml",
        "security/ir.model.access.csv",
        "data/dry_cleaning_sequence.xml",
        "views/dry_cleaning_actions.xml",
        "views/dry_cleaning_menus.xml",
        "views/dry_cleaning_service_type_views.xml",
        "views/dry_cleaning_order_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "dukaku_dry_cleaning/static/src/js/coming_soon_action.js",
            "dukaku_dry_cleaning/static/src/xml/coming_soon_action.xml",
        ],
    },
    "demo": [],
    "installable": True,
    "application": True,
    "auto_install": False,
}
