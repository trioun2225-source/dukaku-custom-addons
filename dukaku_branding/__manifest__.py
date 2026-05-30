{
    'name': 'Dukaku POS Branding',
    'version': '1.0.0',
    'category': 'Hidden',
    'summary': 'Replaces Odoo branding with Dukaku POS across the UI',
    'author': 'Dukaku',
    'depends': ['web', 'point_of_sale'],
    'data': [
        'views/webclient_templates.xml',
        'data/res_company_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dukaku_branding/static/src/scss/branding.scss',
        ],
        'web.assets_frontend': [
            'dukaku_branding/static/src/scss/branding.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
