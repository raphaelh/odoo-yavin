# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for POS session integration with Yavin."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,protected-access

from odoo import fields
from odoo.tests.common import TransactionCase


class TestYavinPosSession(TransactionCase):
    """Tests for Yavin-related POS session behavior."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        eur = cls.env.ref("base.EUR")
        cls.company = cls.env["res.company"].create(
            {
                "name": "Yavin Session Test Company",
                "currency_id": eur.id,
            }
        )
        cls.env.user.company_ids |= cls.company
        cls.env.user.company_id = cls.company

        chart_template = cls.env["account.chart.template"]._guess_chart_template(
            cls.company.country_id
        )
        if chart_template:
            cls.env["account.chart.template"].try_loading(
                chart_template, company=cls.company, install_demo=False
            )

        cls.bank_journal = cls.env["account.journal"].search(
            [
                ("company_id", "=", cls.company.id),
                ("type", "=", "bank"),
            ],
            limit=1,
        )
        cls.sale_journal = cls.env["account.journal"].search(
            [
                ("company_id", "=", cls.company.id),
                ("type", "in", ("sale", "general")),
            ],
            limit=1,
        )

        cls.payment_method = cls.env["pos.payment.method"].create(
            {
                "name": "Yavin Session Method",
                "company_id": cls.company.id,
                "journal_id": cls.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "local",
                "yavin_ip_address": "127.0.0.1",
            }
        )
        cls.split_payment_method = cls.env["pos.payment.method"].create(
            {
                "name": "Yavin Split Session Method",
                "company_id": cls.company.id,
                "journal_id": cls.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "local",
                "yavin_ip_address": "127.0.0.2",
                "split_transactions": True,
            }
        )
        cls.pos_config = cls.env["pos.config"].create(
            {
                "name": "Yavin Session POS",
                "company_id": cls.company.id,
                "journal_id": cls.sale_journal.id,
                "self_ordering_mode": "nothing",
                "payment_method_ids": [
                    fields.Command.link(cls.payment_method.id),
                    fields.Command.link(cls.split_payment_method.id),
                ],
            }
        )
        cls.pos_session = cls.env["pos.session"].create(
            {
                "config_id": cls.pos_config.id,
                "user_id": cls.env.user.id,
                "company_id": cls.company.id,
                "name": "Yavin Session",
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Session Customer"})
        cls.pricelist = cls.pos_config.pricelist_id or cls.env["product.pricelist"].create(
            {
                "name": "Yavin Session Pricelist",
                "currency_id": cls.company.currency_id.id,
            }
        )

    def _create_order(self, name, partner=None):
        return self.env["pos.order"].create(
            {
                "name": name,
                "session_id": self.pos_session.id,
                "company_id": self.company.id,
                "partner_id": (partner or self.partner).id,
                "amount_tax": 0.0,
                "amount_total": 10.0,
                "amount_paid": 10.0,
                "amount_return": 0.0,
                "pricelist_id": self.pricelist.id,
            }
        )

    def test_loader_params_pos_payment_method_include_yavin_fields(self):
        fields_list = self.pos_session._loader_params_pos_payment_method()["search_params"][
            "fields"
        ]

        self.assertIn("yavin_ip_address", fields_list)
        self.assertIn("yavin_connection_mode", fields_list)
        self.assertIn("yavin_effective_connection_mode", fields_list)
        self.assertIn("yavin_display_tip", fields_list)
        self.assertIn("yavin_timeout_ms", fields_list)
        self.assertIn("yavin_reversal_timeout_ms", fields_list)

    def test_get_split_receivable_vals_includes_card_info_in_label(self):
        order = self._create_order("Order/SPLIT")
        payment = self.env["pos.payment"].create(
            {
                "name": "PAY-SPLIT",
                "pos_order_id": order.id,
                "payment_method_id": self.split_payment_method.id,
                "amount": 10.0,
                "payment_date": fields.Datetime.now(),
                "card_type": "visa",
                "yavin_issuer": "swile",
            }
        )

        vals = self.pos_session._get_split_receivable_vals(payment, 10.0, 10.0)

        self.assertEqual(
            vals["name"],
            f"{self.pos_session.name} - {self.split_payment_method.name} (Visa / Swile)",
        )

    def test_get_combine_receivable_vals_deduplicates_and_sorts_card_infos(self):
        first_order = self._create_order("Order/COMBINE/1")
        second_order = self._create_order("Order/COMBINE/2")
        self.env["pos.payment"].create(
            {
                "name": "PAY-COMBINE-1",
                "pos_order_id": first_order.id,
                "payment_method_id": self.payment_method.id,
                "amount": 7.0,
                "payment_date": fields.Datetime.now(),
                "card_type": "visa",
                "yavin_issuer": "swile",
            }
        )
        self.env["pos.payment"].create(
            {
                "name": "PAY-COMBINE-2",
                "pos_order_id": second_order.id,
                "payment_method_id": self.payment_method.id,
                "amount": 3.0,
                "payment_date": fields.Datetime.now(),
                "card_type": "cb",
                "yavin_issuer": "edenred",
            }
        )
        self.env["pos.payment"].create(
            {
                "name": "PAY-COMBINE-3",
                "pos_order_id": second_order.id,
                "payment_method_id": self.payment_method.id,
                "amount": 2.0,
                "payment_date": fields.Datetime.now(),
                "card_type": "visa",
                "yavin_issuer": "swile",
            }
        )

        vals = self.pos_session._get_combine_receivable_vals(self.payment_method, 12.0, 12.0)

        self.assertEqual(
            vals["name"],
            f"{self.pos_session.name} - {self.payment_method.name} (CB / Edenred / Visa / Swile)",
        )
