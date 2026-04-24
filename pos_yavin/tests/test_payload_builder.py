# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for Yavin API payload builder."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,too-few-public-methods

from odoo.tests.common import TransactionCase
from odoo.addons.pos_yavin.models.yavin.api.payload_builder import (
    YavinPayloadBuilder,
)


class TestVersionProviderStub:
    """Stub POS version provider for payload builder tests."""
    @staticmethod
    def get_pos_version():
        return "17.0.test"


class TestYavinPayloadBuilder(TransactionCase):
    """Tests for :class:`YavinPayloadBuilder`."""
    def setUp(self):
        super().setUp()
        self.builder = YavinPayloadBuilder(TestVersionProviderStub())

    def test_build_payment_payload_with_reference_and_partial_customer(self):
        payload = self.builder.build_payment_payload(
            {
                "order_uid": "ORDER1",
                "payment_id": "PAY1",
                "cashier_name": "Alice",
                "attempt_number": 3,
                "customer": {
                    "firstName": "Jane",
                    "email": "jane@example.com",
                    "phone": "",
                },
            },
            1234,
            None,
        )

        self.assertEqual(payload["amount"], 1234)
        self.assertEqual(payload["cartId"], "ORDER1")
        self.assertEqual(payload["transactionType"], "debit")
        self.assertEqual(payload["idempotentUuid"], "ORDER1-PAY1-3")
        self.assertEqual(payload["reference"], "Alice")
        self.assertEqual(
            payload["vendor"],
            {"softwareVersion": "17.0.test", "softwareName": "Odoo POS"},
        )
        self.assertEqual(
            payload["customer"],
            {"firstName": "Jane", "email": "jane@example.com"},
        )

    def test_build_payment_payload_omits_empty_optional_fields(self):
        payload = self.builder.build_payment_payload(
            {
                "order_uid": "ORDER2",
                "payment_id": "PAY2",
                "customer": {},
            },
            500,
            None,
        )

        self.assertEqual(payload["idempotentUuid"], "ORDER2-PAY2-1")
        self.assertNotIn("reference", payload)
        self.assertNotIn("customer", payload)

    def test_build_abort_payload(self):
        payload = self.builder.build_abort_payload("ORDER3", "PAY3", attempt_number=2)

        self.assertEqual(payload, {"idempotentUuid": "ORDER3-PAY3-2"})

    def test_build_reversal_payload(self):
        payload = self.builder.build_reversal_payload(
            750,
            "TX-ORIGINAL",
            "ORDER4",
            "PAY4",
            attempt=4,
        )

        self.assertEqual(
            payload,
            {
                "amount": 750,
                "initialTransactionId": "TX-ORIGINAL",
                "idempotentUuid": "ORDER4-PAY4-4",
                "vendor": {
                    "softwareVersion": "17.0.test",
                    "softwareName": "Odoo POS",
                },
            },
        )
