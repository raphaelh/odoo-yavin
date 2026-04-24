# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for Yavin payment validation helpers."""

# pylint: disable=import-error,missing-function-docstring,invalid-name

from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.pos_yavin.models.yavin_hosting import yavin_is_odoo_sh_environment
from odoo.addons.pos_yavin.models.yavin.validation import YavinPaymentValidator


class TestYavinPaymentValidator(TransactionCase):
    """Tests for :class:`YavinPaymentValidator`."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.validator = YavinPaymentValidator(cls.env)
        cls.company = cls.env.company
        cls.currency = cls.env.ref("base.EUR")

    def test_validate_payment_method_missing_id(self):
        payment_method, error = self.validator.validate_payment_method({})
        self.assertFalse(payment_method)
        self.assertEqual(error["operation_status"], "issue")

    def test_validate_payment_method_not_found(self):
        payment_method, error = self.validator.validate_payment_method(
            {"payment_method_id": 99999999}
        )
        self.assertFalse(payment_method)
        self.assertEqual(error["operation_status"], "issue")

    def test_resolve_ip_address_missing_config(self):
        method = SimpleNamespace(
            yavin_ip_address="",
            display_name="Test Method",
            id=42,
        )
        resolved_ip, error = self.validator.resolve_ip_address(method)
        self.assertFalse(resolved_ip)
        self.assertEqual(error["operation_status"], "issue")

    def test_resolve_ip_address_validation_error_returns_issue(self):
        method = SimpleNamespace(
            yavin_ip_address="invalid-host",
            display_name="Test Method",
            id=42,
        )
        with patch(
            "odoo.addons.pos_yavin.models.yavin.validation."
            "YavinAddressResolver.resolve_address",
            side_effect=ValidationError("bad address"),
        ):
            resolved_ip, error = self.validator.resolve_ip_address(method)
        self.assertFalse(resolved_ip)
        self.assertEqual(error["operation_status"], "issue")
        self.assertIn("bad address", error["error_message"])

    def test_validate_currency_unsupported_raises(self):
        unsupported_currency = SimpleNamespace(name="USD")
        with self.assertRaises(ValidationError):
            self.validator.validate_currency(unsupported_currency)

    def test_validate_amount_negative_refund_without_reference(self):
        error = self.validator.validate_amount(-1.0, self.currency, operation="payment")
        self.assertEqual(error["operation_status"], "issue")

    def test_validate_amount_zero_rejected(self):
        error = self.validator.validate_amount(0.0, self.currency, operation="payment")
        self.assertEqual(error["operation_status"], "issue")

    def test_validate_cloud_credentials_ok(self):
        method = SimpleNamespace(
            yavin_effective_connection_mode="cloud",
            yavin_terminal_serial="  SN123  ",
            yavin_cloud_api_key="  super-secret-123  ",
            display_name="M",
        )
        creds, error = self.validator.validate_cloud_credentials(method)
        self.assertIsNone(error)
        self.assertEqual(creds, ("SN123", "super-secret-123"))

    def test_validate_cloud_credentials_missing_serial(self):
        method = SimpleNamespace(
            yavin_effective_connection_mode="cloud",
            yavin_terminal_serial="",
            yavin_cloud_api_key="secret",
            display_name="M",
        )
        creds, error = self.validator.validate_cloud_credentials(method)
        self.assertIsNone(creds)
        self.assertEqual(error["operation_status"], "issue")

    def test_validate_cloud_credentials_wrong_mode(self):
        method = SimpleNamespace(
            yavin_effective_connection_mode="local",
            yavin_terminal_serial="SN",
            yavin_cloud_api_key="secret",
            display_name="M",
        )
        creds, error = self.validator.validate_cloud_credentials(method)
        self.assertIsNone(creds)
        self.assertEqual(error["operation_status"], "issue")

    def test_validate_cloud_credentials_rejects_placeholder_key(self):
        method = SimpleNamespace(
            yavin_effective_connection_mode="cloud",
            yavin_terminal_serial="SN123",
            yavin_cloud_api_key="  changeMe  ",
            display_name="M",
        )
        creds, error = self.validator.validate_cloud_credentials(method)
        self.assertIsNone(creds)
        self.assertEqual(error["operation_status"], "issue")
        self.assertIn("invalid", error["error_message"].lower())

    def test_yavin_is_odoo_sh_environment_returns_bool(self):
        self.assertIsInstance(yavin_is_odoo_sh_environment(), bool)
