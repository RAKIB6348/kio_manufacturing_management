# -*- coding: utf-8 -*-
{
    'name': 'KIO Manufacturing Management',
    'version': '17.0.1.0.0',
    'category': 'Manufacturing/Manufacturing',
    'summary': 'Manufacturing approval workflow and role-based buttons',
    'description': """
KIO Manufacturing Management
============================
Adds manufacturing order approval workflow and role-based header actions.
""",
    'author': 'Kendroo Limited',
    'website': 'https://kendroo.io',
    'depends': ['kio_purchase_management', 'mrp', 'product_barcode_36_labels', 'kio_attributes_value_code'],
    'data': [
        'security/ir.model.access.csv',
        'security/mrp_production_rules.xml',
        'report/product_serial_number_label_report.xml',
        'wizard/mrp_serial_number_label_layout_views.xml',
        'views/mrp_production_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'kio_manufacturing_management/static/src/js/finished_good_verification_barcode.js',
            'kio_manufacturing_management/static/src/scss/finished_good_verification.scss',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'OPL-1',
}
