{
    'name': 'Dukaku Barcode & QR',
    'version': '19.0.1.0.0',
    'summary': 'Auto-assign EAN-13/Code128 barcodes, thermal label printing, QR on digital receipts',
    'category': 'Point of Sale',
    'author': 'Dukaku POS',
    'website': 'https://dukaku.com',
    'license': 'LGPL-3',
    'depends': [
        'product',
        'point_of_sale',
        'barcodes',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/product_views.xml',
        'views/res_config_settings_views.xml',
        'report/report_paperformat.xml',
        'report/report_product_label.xml',
    ],
    'assets': {
        'point_of_sale.assets_prod': [
            'dukaku_barcode/static/src/app/screens/receipt_screen/receipt/dukaku_order_receipt.js',
            'dukaku_barcode/static/src/app/screens/receipt_screen/receipt/dukaku_order_receipt.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
