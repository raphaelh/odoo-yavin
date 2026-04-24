# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Browser tests for pos_yavin JavaScript assets."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,protected-access

import logging

from odoo import fields
from odoo.tests import tagged, HttpCase

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class YavinJSTestSuite(HttpCase):
    """Test suite for JavaScript tests of pos_yavin module."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = cls.env.ref("base.user_admin")
        cls.js_test_login = "yavin_js_test"
        # Create a new company with EUR currency (supported by Yavin)
        eur = cls.env.ref("base.EUR")
        cls.company = cls.env["res.company"].create(
            {
                "name": "Yavin JS Test Company",
                "currency_id": eur.id,
            }
        )
        cls.admin_user.company_ids |= cls.company
        cls.admin_user.company_id = cls.company
        cls.js_test_user = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Yavin JS Test User",
                "login": cls.js_test_login,
                "password": cls.js_test_login,
                "company_id": cls.company.id,
                "company_ids": [fields.Command.link(cls.company.id)],
                "groups_id": [fields.Command.set([cls.env.ref("base.group_system").id])],
            }
        )
        env = cls.env(user=cls.admin_user)

        # Install chart of accounts for the company (required for POS)
        chart_template = env["account.chart.template"]._guess_chart_template(
            cls.company.country_id
        )
        if chart_template:
            env["account.chart.template"].try_loading(
                chart_template, company=cls.company, install_demo=False
            )

        # Create bank journal
        cls.bank_journal = env["account.journal"].search(
            [
                ("company_id", "=", cls.company.id),
                ("type", "=", "bank"),
            ],
            limit=1,
        )
        if not cls.bank_journal:
            cls.bank_journal = env["account.journal"].create(
                {
                    "name": "Yavin Bank JS",
                    "code": "YAVBJS",
                    "type": "bank",
                    "company_id": cls.company.id,
                    "currency_id": eur.id,
                }
            )

        # Create sale journal
        cls.sale_journal = env["account.journal"].search(
            [
                ("company_id", "=", cls.company.id),
                ("type", "in", ("sale", "general")),
            ],
            limit=1,
        )
        if not cls.sale_journal:
            cls.sale_journal = env["account.journal"].create(
                {
                    "name": "Yavin Sales JS",
                    "code": "YAVSJS",
                    "type": "sale",
                    "company_id": cls.company.id,
                    "currency_id": eur.id,
                }
            )

        # Create Yavin payment method
        cls.payment_method = env["pos.payment.method"].create(
            {
                "name": "Yavin JS Test Method",
                "company_id": cls.company.id,
                "journal_id": cls.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "local",
                "yavin_ip_address": "127.0.0.1",
            }
        )

        # Create POS config
        cls.pos_config = env["pos.config"].create(
            {
                "name": "Yavin JS POS",
                "company_id": cls.company.id,
                "journal_id": cls.sale_journal.id,
                "self_ordering_mode": "nothing",
                "payment_method_ids": [fields.Command.link(cls.payment_method.id)],
            }
        )

        # Create a test product
        env["product.product"].create(
            {
                "name": "Test Product JS",
                "available_in_pos": True,
                "list_price": 10.0,
            }
        )

    def test_yavin_js(self):
        """Run JavaScript QUnit tests for pos_yavin module."""
        # Open a POS session to ensure the environment is properly set up
        self.pos_config.with_user(self.admin_user).open_ui()
        if self.pos_config.current_session_id:
            self.pos_config.current_session_id.with_user(self.admin_user).set_cashbox_pos(0, None)

        # Run JavaScript tests for pos_yavin module
        # The tests are located in static/tests/payment_yavin_tests.js,
        # payment_yavin_polling_tests.js (Cloud RPC polling), and related modules.
        # The QUnit module names include "pos_yavin PaymentYavin",
        # "pos_yavin CloudPolling", and "pos_yavin YavinTipHandler".
        # Use POS test suite which includes all POS dependencies needed by the
        # modules. Run all tests first to verify they are loaded, then we can
        # filter.
        self.browser_js(
            "/pos/ui/tests?mod=pos_yavin",
            "",
            "",
            login=self.js_test_login,
            timeout=1800,
        )
