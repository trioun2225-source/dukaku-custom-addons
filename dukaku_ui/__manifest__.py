{
    'name': 'Dukaku UI',
    'version': '1.0',
    'summary': 'Dukaku brand theme, dark mode toggle, hides Discuss, sets POS as home',
    'author': 'Dukaku',
    'category': 'Technical',
    'depends': ['mail', 'point_of_sale', 'web'],
    'data': [
        'views/hide_discuss.xml',
        'views/assets.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dukaku_ui/static/src/scss/dukaku_theme.scss',
            'dukaku_ui/static/src/scss/dukaku_dark.scss',
            'dukaku_ui/static/src/js/dukaku_toggle.js',
            'dukaku_ui/static/src/xml/dukaku_toggle.xml',
        ],
        'web.assets_frontend': [
            'dukaku_ui/static/src/scss/dukaku_login_light.scss',
            'dukaku_ui/static/src/scss/dukaku_login_dark.scss',
        ],
        'web.assets_frontend_minimal': [
            'dukaku_ui/static/src/js/dukaku_login_toggle.js',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
