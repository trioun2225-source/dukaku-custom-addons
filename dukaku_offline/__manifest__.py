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
    """,
    'author': 'Dukaku',
    'depends': ['point_of_sale'],
    'data': ['views/pos_index_patch.xml'],
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
