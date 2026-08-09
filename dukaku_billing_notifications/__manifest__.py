{
    'name': 'Dukaku Billing Notifications',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'POS banner for subscription billing warnings, driven by the Dukaku billing daemon',
    'description': """
        Surfaces subscription-billing warnings inside the POS as a non-blocking toast.

        - Localhost notify endpoint (/dukaku_billing/notify) the billing daemon POSTs to,
          authenticated by a shared secret (ir.config_parameter dukaku_billing.notify_secret)
          via constant-time compare. One current notification is stored per database.
        - POS polls (/dukaku_billing/poll) on load and every ~5 min and renders a toast
          styled by urgency (info/warning/critical) with Dismiss + Renew actions.
        - Per-user, per-cycle dismissal (server-side): dismissing hides the banner until
          the daemon fires a new cycle_key; on the final day it re-fires every 15 min.
    """,
    'author': 'Dukaku',
    'depends': ['point_of_sale'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'dukaku_billing_notifications/static/src/js/billing_notification_service.js',
            'dukaku_billing_notifications/static/src/js/billing_notification_banner.js',
            'dukaku_billing_notifications/static/src/js/navbar_patch.js',
            'dukaku_billing_notifications/static/src/xml/templates.xml',
            'dukaku_billing_notifications/static/src/scss/billing_notification.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
