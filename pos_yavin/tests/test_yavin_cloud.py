# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for Yavin Cloud webhook correlation and configuration."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,protected-access

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestYavinCloud(TransactionCase):
    """Yavin Cloud model and payment method behaviour."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        eur = cls.env.ref("base.EUR")
        cls.company = cls.env["res.company"].create(
            {
                "name": "Yavin Cloud Test Co",
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
                    "name": "Yavin Cloud Bank",
                    "code": "YCVB",
                    "type": "bank",
                    "company_id": cls.company.id,
                    "currency_id": eur.id,
                }
            )

    def test_process_webhook_marks_transaction_done(self):
        method = self.env["pos.payment.method"].create(
            {
                "name": "Yavin Cloud Method",
                "company_id": self.company.id,
                "journal_id": self.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "cloud",
                "yavin_terminal_serial": "SERIAL1",
                "yavin_cloud_api_key": "secret-key",
            }
        )
        self.assertTrue(method.yavin_webhook_token)

        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "ORDER-P1-1",
                "cart_id": "ORDER",
                "cloud_transaction_id": "TID99",
                "currency_id": self.company.currency_id.id,
            }
        )
        payload = {
            "status": "ok",
            "trs_id": "TID99",
            "cartId": "ORDER",
            "client_ticket": "ok",
        }
        self.env["yavin.cloud.transaction"]._yavin_process_webhook(
            method.yavin_webhook_token, payload
        )
        tx.invalidate_recordset()
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.result_payload.get("trs_id"), "TID99")

    def test_check_yavin_cloud_requires_serial_and_key(self):
        with self.assertRaises(ValidationError):
            self.env["pos.payment.method"].create(
                {
                    "name": "Bad Cloud",
                    "company_id": self.company.id,
                    "journal_id": self.bank_journal.id,
                    "use_payment_terminal": "yavin",
                    "yavin_connection_mode": "cloud",
                    "yavin_terminal_serial": "",
                    "yavin_cloud_api_key": "",
                }
            )

    def test_cloud_payment_payload_uses_camelcase_for_v4(self):
        """Yavin Cloud v4 expects camelCase JSON (not snake_case)."""
        from odoo.addons.pos_yavin.models.yavin.api.cloud_payload import (
            YavinCloudPayloadBuilder,
        )
        from odoo.addons.pos_yavin.models.yavin.version.provider import (
            YavinVersionProvider,
        )

        currency = self.env.ref("base.EUR")
        builder = YavinCloudPayloadBuilder(YavinVersionProvider())
        data = {
            "order_uid": "O1",
            "payment_id": "P1",
            "attempt_number": 1,
            "customer": {"firstName": "Ann", "lastName": "Bee"},
        }
        payload, iuid = builder.build_payment_payload(data, 1500, currency, False)
        self.assertEqual(iuid, "O1-P1-1")
        self.assertEqual(payload["transactionType"], "debit")
        self.assertEqual(payload["currencyCode"], "EUR")
        self.assertEqual(payload["cartId"], "O1")
        self.assertEqual(payload["idempotentUuid"], "O1-P1-1")
        self.assertFalse(payload["enableGiftScreen"])
        self.assertEqual(payload["giftAmount"], 0)
        self.assertEqual(payload["vendor"]["softwareName"], "Odoo POS")
        self.assertEqual(payload["customer"]["firstName"], "Ann")
        self.assertNotIn("transaction_type", payload)
        self.assertNotIn("currency_code", payload)

    def test_discover_action_warns_in_cloud_mode(self):
        method = self.env["pos.payment.method"].create(
            {
                "name": "Yavin Cloud Discover",
                "company_id": self.company.id,
                "journal_id": self.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "cloud",
                "yavin_terminal_serial": "SERIAL1",
                "yavin_cloud_api_key": "secret-key",
            }
        )
        action = method.yavin_discover_terminals_action()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["params"]["type"], "warning")
