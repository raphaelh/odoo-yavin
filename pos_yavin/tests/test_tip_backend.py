# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for Yavin tip handling on the POS backend."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,protected-access

from odoo import fields
from odoo.tests.common import TransactionCase


class TestYavinBackendExport(TransactionCase):
    """Tests for tip-related data exported to the POS frontend."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create a new company with EUR currency (supported by Yavin)
        eur = cls.env.ref("base.EUR")
        cls.company = cls.env["res.company"].create(
            {
                "name": "Yavin Test Company",
                "currency_id": eur.id,
            }
        )
        cls.env.user.company_ids |= cls.company
        cls.env.user.company_id = cls.company
        cls.bank_journal = cls.env["account.journal"].search(
            [
                ("company_id", "=", cls.company.id),
                ("type", "=", "bank"),
            ],
            limit=1,
        )
        if not cls.bank_journal:
            cls.bank_journal = cls.env["account.journal"].create(
                {
                    "name": "Yavin Bank",
                    "code": "YAVB",
                    "type": "bank",
                    "company_id": cls.company.id,
                    "currency_id": eur.id,
                }
            )
        cls.sale_journal = cls.env["account.journal"].search(
            [
                ("company_id", "=", cls.company.id),
                ("type", "in", ("sale", "general")),
            ],
            limit=1,
        )
        if not cls.sale_journal:
            cls.sale_journal = cls.env["account.journal"].create(
                {
                    "name": "Yavin Sales",
                    "code": "YAVS",
                    "type": "sale",
                    "company_id": cls.company.id,
                    "currency_id": eur.id,
                }
            )
        cls.payment_method = cls.env["pos.payment.method"].create(
            {
                "name": "Yavin Export Method",
                "company_id": cls.company.id,
                "journal_id": cls.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "local",
                "yavin_ip_address": "127.0.0.1",
            }
        )
        cls.pos_config = cls.env["pos.config"].create(
            {
                "name": "Yavin POS (export)",
                "company_id": cls.company.id,
                "journal_id": cls.sale_journal.id,
                "self_ordering_mode": "nothing",
                "payment_method_ids": [fields.Command.link(cls.payment_method.id)],
            }
        )
        if not cls.pos_config.pricelist_id:
            cls.pricelist = cls.env["product.pricelist"].create(
                {
                    "name": "Yavin Pricelist",
                    "currency_id": cls.company.currency_id.id,
                }
            )
            cls.pos_config.pricelist_id = cls.pricelist.id
        else:
            cls.pricelist = cls.pos_config.pricelist_id
        cls.pos_session = cls.env["pos.session"].create(
            {
                "config_id": cls.pos_config.id,
                "user_id": cls.env.user.id,
                "company_id": cls.company.id,
                "name": "Yavin Export Session",
            }
        )
        cls.order = cls.env["pos.order"].create(
            {
                "name": "Order/YAV",
                "session_id": cls.pos_session.id,
                "company_id": cls.company.id,
                "amount_tax": 0.0,
                "amount_total": 10.0,
                "amount_paid": 10.0,
                "amount_return": 0.0,
                "pricelist_id": cls.pricelist.id,
            }
        )

    def test_export_for_ui_contains_yavin_issuer(self):
        payment = self.env["pos.payment"].create(
            {
                "name": "YAVPAY",
                "pos_order_id": self.order.id,
                "payment_method_id": self.payment_method.id,
                "amount": 10.0,
                "payment_date": fields.Datetime.now(),
                "payment_status": "done",
                "yavin_issuer": "Swile",
            }
        )
        payload = payment._export_for_ui(payment)
        self.assertEqual(payload["yavin_issuer"], "Swile")

    def test_payment_fields_carry_yavin_issuer(self):
        ui_paymentline = {
            "amount": 5.0,
            "name": fields.Datetime.now().isoformat(),
            "payment_method_id": self.payment_method.id,
            "yavin_issuer": "Edenred",
        }
        values = self.order._payment_fields(self.order, ui_paymentline)
        self.assertEqual(values["yavin_issuer"], "Edenred")
