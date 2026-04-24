# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for Yavin API response parsing."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,too-few-public-methods

from odoo import _
from odoo.tests.common import TransactionCase

from odoo.addons.pos_yavin.models.yavin.api.response_parser import (
    YavinResponseParser,
)
from odoo.addons.pos_yavin.models.yavin.formatting.amount_converter import (
    YavinAmountConverter,
)


class TestYavinResponseParser(TransactionCase):
    """Tests for :class:`YavinResponseParser`."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.env.ref("base.EUR")
        cls.parser = YavinResponseParser(YavinAmountConverter(), cls.env)

    def test_parse_payment_response_success_without_tip(self):
        result = self.parser.parse_payment_response(
            {
                "status": "ok",
                "transactionId": "TX-1",
                "scheme": "VISA",
                "issuer": "Swile",
                "clientCardTicket": "ticket-content",
            },
            self.currency,
        )

        self.assertEqual(result["operation_status"], "success")
        self.assertEqual(result["transaction_id"], "TX-1")
        self.assertEqual(result["card_type"], "VISA")
        self.assertEqual(result["yavin_issuer"], "Swile")
        self.assertEqual(result["ticket"], "ticket-content")
        self.assertNotIn("gift_amount", result)

    def test_parse_payment_response_success_with_tip(self):
        result = self.parser.parse_payment_response(
            {
                "status": "ok",
                "transactionId": "TX-2",
                "scheme": "CB",
                "giftAmount": 250,
            },
            self.currency,
        )

        self.assertEqual(result["operation_status"], "success")
        self.assertEqual(result["transaction_id"], "TX-2")
        self.assertEqual(result["card_type"], "CB")
        self.assertEqual(result["gift_amount"], 2.5)

    def test_parse_payment_response_failure_with_explicit_message(self):
        result = self.parser.parse_payment_response(
            {"status": "ko", "message": "Declined"},
            self.currency,
        )

        self.assertEqual(result["operation_status"], "failure")
        self.assertEqual(result["error_message"], "Declined")

    def test_parse_payment_response_failure_without_message_uses_fallback(self):
        result = self.parser.parse_payment_response(
            {"status": "ko"},
            self.currency,
        )

        self.assertEqual(result["operation_status"], "failure")
        self.assertEqual(
            result["error_message"],
            _("The payment transaction has failed."),
        )

    def test_parse_reversal_response_success(self):
        result = self.parser.parse_reversal_response({"status": "ok"})

        self.assertEqual(result["operation_status"], "success")

    def test_parse_reversal_response_failure_without_message_uses_fallback(self):
        result = self.parser.parse_reversal_response({"status": "ko"})

        self.assertEqual(result["operation_status"], "failure")
        self.assertEqual(
            result["error_message"],
            _("The reversal transaction has failed."),
        )

    def test_parse_cloud_webhook_payload_success(self):
        result = self.parser.parse_cloud_webhook_payload(
            {
                "status": "ok",
                "trs_id": "TX-CLOUD-1",
                "client_ticket": "line1",
                "gift_amount": 100,
                "scheme": "VISA",
            },
            self.currency,
        )
        self.assertEqual(result["operation_status"], "success")
        self.assertEqual(result["transaction_id"], "TX-CLOUD-1")
        self.assertEqual(result["ticket"], "line1")
        self.assertEqual(result["gift_amount"], 1.0)

    def test_parse_cloud_webhook_payload_failure(self):
        result = self.parser.parse_cloud_webhook_payload(
            {"status": "ko", "message": "Declined"},
            self.currency,
        )
        self.assertEqual(result["operation_status"], "failure")
        self.assertEqual(result["error_message"], "Declined")
