# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "POS: Yavin payment terminal",
    "version": "17.0.1.2.6",
    "category": "Point of Sale",
    "license": "AGPL-3",
    "summary": "Add support for Yavin payment terminal (Local API and Cloud API)",
    "author": "Raphaël HUCK",
    "website": "https://github.com/raphaelh/odoo-yavin",
    "images": ["static/description/images/main_screenshot.png"],
    # pos_self_order extends pos.config (e.g. self_ordering_mode NOT NULL on recent DBs)
    "depends": ["point_of_sale", "pos_self_order"],
    "data": [
        "security/ir.model.access.csv",
        "data/yavin_cron_data.xml",
        "data/yavin_payment_method_image.xml",
        "views/pos_payment_method.xml",
        "wizard/discover_wizard.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pos_yavin/static/src/wizard/discover_wizard.css",
            "pos_yavin/static/src/wizard/discover_wizard.js",
        ],
        "point_of_sale._assets_pos": [
            "pos_yavin/static/src/payment/lifecycle_utils.js",
            "pos_yavin/static/src/payment/payment_state.js",
            "pos_yavin/static/src/payment/tip_handler.js",
            "pos_yavin/static/src/payment/payment_cancel.js",
            "pos_yavin/static/src/payment/payment_reversal.js",
            "pos_yavin/static/src/payment/payment_request.js",
            "pos_yavin/static/src/payment/payment_yavin.js",
            "pos_yavin/static/src/overrides/models/models.js",
            "pos_yavin/static/src/overrides/components/order_widget/order_widget.js",
            "pos_yavin/static/src/overrides/components/order_widget/order_widget.xml",
            "pos_yavin/static/src/overrides/components/payment_screen/payment_screen.js",
        ],
        "point_of_sale.assets_qunit_tests": [
            "pos_yavin/static/src/payment/lifecycle_utils.js",
            "pos_yavin/static/src/payment/payment_state.js",
            "pos_yavin/static/src/payment/payment_cancel.js",
            "pos_yavin/static/src/payment/payment_reversal.js",
            "pos_yavin/static/src/payment/payment_request.js",
            "pos_yavin/static/src/wizard/discover_wizard.js",
            "pos_yavin/static/tests/payment_yavin_tests.js",
            "pos_yavin/static/tests/payment_yavin_polling_tests.js",
            "pos_yavin/static/tests/models_yavin_tests.js",
            "pos_yavin/static/tests/discover_wizard_tests.js",
        ],
    },
}
