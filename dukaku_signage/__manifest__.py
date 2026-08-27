{
    'name': 'Dukaku Signage',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Full-screen flyer playlist for smart TVs via a token-gated public URL',
    'description': """
Dukaku Signage
==============
Lets a tenant upload flyer images, order and time them into a playlist, and
display that playlist full-screen on a smart TV through a single public,
token-gated URL (no login).

- signage.flyer: uploaded image + sequence + per-slide display seconds.
- signage.config: one settings record per database (transition style,
  orientation, and the long random secret that is the SOLE access boundary
  for the public routes).
- /signage/display and /signage/image/<id>: public (auth='public') routes,
  gated only by constant-time comparison of ?secret= against
  signage.config.secret. Per the shared-addons architecture on this host,
  these routes are live process-wide as soon as the module is importable
  from custom_addons -- the secret, not DB/tenant scoping, is the boundary.

Depends on 'web' only: no Point of Sale, mail, or barcode coupling.
""",
    'author': 'Dukaku',
    'website': 'https://dukaku.com',
    'license': 'LGPL-3',
    'depends': ['web'],
    'data': [
        'security/ir.model.access.csv',
        'views/signage_flyer_views.xml',
        'views/signage_config_views.xml',
        'views/signage_menu.xml',
        'templates/signage_display.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
