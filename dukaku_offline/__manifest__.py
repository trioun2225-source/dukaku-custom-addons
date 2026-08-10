{
    'name': 'Dukaku Offline / PWA',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'PWA manifest and hardened service worker for Dukaku POS offline mode',
    'description': """
        Wraps the Dukaku POS as an installable PWA and hardens its offline behaviour:
        - Web app manifest with Dukaku branding (name, icons, theme colour, standalone display)
        - Enhanced service worker: pre-caches app shell on install so a cold offline
          launch works without any redirect or network round-trip
        - Template patch adds <link rel="manifest"> to the POS HTML head, resolving
          the correct config_id at request time (multi-tenant safe, no hardcoding)

        Stage 8 adds a generic, vertical-agnostic offline-operation synchronization
        layer (dukaku.offline.operation + a closed handler registry other Dukaku
        modules register into): idempotent, authenticated, per-user-isolated queue
        processing for offline-queued business operations. Contains no reference to
        any vertical's own models - a vertical module (e.g. dukaku_dry_cleaning)
        depends on this module and registers its own handlers, never the reverse.
    """,
    'author': 'Dukaku',
    'depends': ['point_of_sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/pos_index_patch.xml',
        'views/offline_operation_views.xml',
        'data/offline_operation_cron.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'dukaku_offline/static/src/app/offline_guard.js',
            'dukaku_offline/static/src/app/data_service_patch.js',
            'dukaku_offline/static/src/app/pos_store_patch.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
