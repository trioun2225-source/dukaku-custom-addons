{
    "name": "Dukaku POS Access Restriction",
    "version": "19.0.1.0.0",
    "summary": "Restrict POS Users to explicitly assigned POS shops",
    "category": "Point of Sale",
    "author": "Dukaku",
    "depends": ["point_of_sale"],
    "data": [
        "security/pos_config_security.xml",
        "views/res_users_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
