# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for POS payment method and Yavin backend hooks."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,protected-access,too-many-public-methods

import ast
from pathlib import Path
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.addons.pos_yavin.models.yavin import (
    YavinPaymentValidator,
    YavinDataExtractor,
)


class TestPosPaymentMethod(TransactionCase):
    """Test suite for Pos Payment Method and Yavin integration."""

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
                "name": "Yavin Test Method",
                "company_id": cls.company.id,
                "journal_id": cls.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "local",
                "yavin_ip_address": "127.0.0.1",
            }
        )
        cls.pos_config = cls.env["pos.config"].create(
            {
                "name": "Yavin POS",
                "company_id": cls.company.id,
                "journal_id": cls.sale_journal.id,
                "self_ordering_mode": "nothing",
                "payment_method_ids": [fields.Command.link(cls.payment_method.id)],
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

    def _make_payment_payload(self, **overrides):
        payload = {
            "payment_method_id": self.payment_method.id,
            "amount": 10.0,
            "currency_id": self.company.currency_id.id,
            "payment_id": "PAYLINE",
            "order_uid": "ORDER123",
            "timeout": 1000,
        }
        payload.update(overrides)
        return payload

    def _make_abort_payload(self, **overrides):
        payload = {
            "payment_method_id": self.payment_method.id,
            "order_uid": "ORDER123",
            "payment_id": "PAYLINE",
            "attempt_number": 1,
        }
        payload.update(overrides)
        return payload

    def test_validate_currency_rejects_unsupported(self):
        usd = self.env.ref("base.USD")
        validator = YavinPaymentValidator(self.env)
        with self.assertRaises(ValidationError):
            validator.validate_currency(usd)

    def test_validate_payment_method_rejects_unknown_id(self):
        validator = YavinPaymentValidator(self.env)
        payment_method, error = validator.validate_payment_method(
            {"payment_method_id": 999999},
        )
        self.assertFalse(payment_method)
        self.assertEqual(error["operation_status"], "issue")
        self.assertTrue(error["error_message"])
        self.assertIn("999999", error["error_message"])

    def test_extract_customer_data(self):
        partner = self.env["res.partner"].create(
            {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "0102030405",
            }
        )
        extractor = YavinDataExtractor(self.env)
        payload = extractor.extract_customer_data(partner.id)
        self.assertDictEqual(
            payload,
            {
                "firstName": "Jane",
                "lastName": "Doe",
                "email": "jane@example.com",
                "phone": "0102030405",
            },
        )

    def test_extract_customer_data_returns_none_when_empty(self):
        partner = self.env["res.partner"].create({"name": ""})
        extractor = YavinDataExtractor(self.env)
        payload = extractor.extract_customer_data(partner.id)
        self.assertIsNone(payload)

    def test_extract_cashier_name(self):
        extractor = YavinDataExtractor(self.env)
        cashier = extractor.extract_cashier_name(self.pos_session.id)
        self.assertEqual(cashier, self.env.user.name or "")

    def test_yavin_send_payment_calls_client(self):
        payload = {
            "payment_method_id": self.payment_method.id,
            "amount": 10.0,
            "currency_id": self.company.currency_id.id,
            "payment_id": "PAYLINE",
            "order_uid": "ORDER123",
            "timeout": 1000,
        }
        orchestrator = self.payment_method._get_yavin_orchestrator()
        with patch.object(
            orchestrator,
            "send_payment",
            return_value={"operation_status": "success"},
        ) as send_mock, patch.object(
            type(self.payment_method),
            "_get_yavin_orchestrator",
            return_value=orchestrator,
        ):
            result = self.payment_method.yavin_send_payment(payload.copy())
        self.assertEqual(result["operation_status"], "success")
        send_mock.assert_called_once_with(payload)

    def test_yavin_send_payment_handles_missing_amount(self):
        data = {
            "payment_method_id": self.payment_method.id,
            "amount": 0.0,
            "currency_id": self.company.currency_id.id,
        }
        with patch.object(
            YavinPaymentValidator,
            "resolve_ip_address",
            return_value=(self.payment_method.yavin_ip_address, None),
        ):
            result = self.payment_method.yavin_send_payment(data)

        self.assertEqual(result["operation_status"], "issue")
        self.assertTrue(result["error_message"])

    def test_yavin_send_payment_missing_ip_address(self):
        payment_method_no_ip = self.env["pos.payment.method"].create(
            {
                "name": "Yavin No IP",
                "company_id": self.company.id,
                "journal_id": self.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "local",
                "yavin_ip_address": "127.0.0.1",
            }
        )
        self.env.cr.execute(
            "UPDATE pos_payment_method SET yavin_ip_address = NULL WHERE id = %s",
            (payment_method_no_ip.id,),
        )
        self.env.invalidate_all()
        payload = self._make_payment_payload(payment_method_id=payment_method_no_ip.id)

        result = payment_method_no_ip.yavin_send_payment(payload)
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn(payment_method_no_ip.display_name, result["error_message"])

    def test_yavin_send_payment_resolve_address_failure(self):
        payload = self._make_payment_payload()
        with patch.object(
            YavinPaymentValidator,
            "resolve_ip_address",
            return_value=(
                None,
                {
                    "operation_status": "issue",
                    "error_message": "Invalid host",
                },
            ),
        ):
            result = self.payment_method.yavin_send_payment(payload)
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Invalid host", result["error_message"])

    def test_yavin_send_payment_includes_customer_and_cashier(self):
        partner = self.env["res.partner"].create(
            {"name": "Jane Smith", "email": "js@example.com"}
        )
        payload = self._make_payment_payload(
            partner_id=partner.id,
            session_id=self.pos_session.id,
        )
        with patch.object(
            YavinPaymentValidator,
            "resolve_ip_address",
            return_value=("10.0.0.2", None),
        ), patch(
            "odoo.addons.pos_yavin.models.yavin.application."
            "payment_orchestrator.YavinAPIClient",
        ) as client_cls, patch(
            "odoo.addons.pos_yavin.models.yavin.application."
            "payment_orchestrator.YavinPaymentOrchestrator._validate_currency",
            return_value=(self.company.currency_id, None),
        ):
            client_instance = client_cls.return_value
            client_instance.send_payment.return_value = {"operation_status": "success"}
            result = self.payment_method.yavin_send_payment(payload.copy())
        self.assertEqual(result["operation_status"], "success")
        send_args = client_instance.send_payment.call_args[0]
        self.assertEqual(send_args[0]["customer"]["firstName"], "Jane")
        self.assertIn("cashier_name", send_args[0])
        self.assertEqual(send_args[0]["cashier_name"], self.env.user.name or "")

    def test_yavin_send_payment_propagates_issue_response(self):
        payload = self._make_payment_payload()
        orchestrator = self.payment_method._get_yavin_orchestrator()
        issue = {
            "operation_status": "issue",
            "error_message": "Timeout",
        }
        with patch.object(
            orchestrator, "send_payment", return_value=issue
        ), patch.object(
            type(self.payment_method),
            "_get_yavin_orchestrator",
            return_value=orchestrator,
        ):
            result = self.payment_method.yavin_send_payment(payload)
        self.assertEqual(result, issue)

    def test_yavin_abort_payment_calls_client(self):
        data = {
            "payment_method_id": self.payment_method.id,
            "order_uid": "ORDER123",
            "payment_id": "PAYLINE",
            "attempt_number": 1,
        }
        orchestrator = self.payment_method._get_yavin_orchestrator()
        with patch.object(
            orchestrator,
            "abort_payment",
            return_value={"operation_status": "success"},
        ) as abort_mock, patch.object(
            type(self.payment_method),
            "_get_yavin_orchestrator",
            return_value=orchestrator,
        ):
            result = self.payment_method.yavin_abort_payment(data.copy())
        self.assertEqual(result["operation_status"], "success")
        abort_mock.assert_called_once_with(data)

    def test_yavin_abort_payment_missing_required_fields(self):
        result = self.payment_method.yavin_abort_payment(
            {"payment_method_id": self.payment_method.id}
        )
        self.assertEqual(result["operation_status"], "issue")

    def test_yavin_abort_payment_missing_ip_address(self):
        self.env.cr.execute(
            "UPDATE pos_payment_method SET yavin_ip_address = NULL WHERE id = %s",
            (self.payment_method.id,),
        )
        self.env.invalidate_all()
        result = self.payment_method.yavin_abort_payment(self._make_abort_payload())
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn(self.payment_method.display_name, result["error_message"])

    def test_yavin_abort_payment_resolve_address_failure(self):
        with patch.object(
            YavinPaymentValidator,
            "resolve_ip_address",
            return_value=(
                None,
                {
                    "operation_status": "issue",
                    "error_message": "Cannot resolve",
                },
            ),
        ):
            result = self.payment_method.yavin_abort_payment(
                self._make_abort_payload()
            )
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Cannot resolve", result["error_message"])

    def test_yavin_abort_payment_calls_client_with_resolved_ip(self):
        payload = self._make_abort_payload()
        with patch.object(
            YavinPaymentValidator,
            "resolve_ip_address",
            return_value=("10.0.0.3", None),
        ), patch(
            "odoo.addons.pos_yavin.models.yavin.application."
            "payment_orchestrator.YavinAPIClient",
        ) as client_cls:
            client_instance = client_cls.return_value
            client_instance.abort_payment.return_value = {"operation_status": "success"}
            result = self.payment_method.yavin_abort_payment(payload.copy())
        self.assertEqual(result["operation_status"], "success")
        client_instance.abort_payment.assert_called_once_with(
            payload["order_uid"],
            payload["payment_id"],
            payload["attempt_number"],
            wait_for_payment=True,
        )

    def test_yavin_abort_payment_propagates_client_error(self):
        payload = self._make_abort_payload()
        orchestrator = self.payment_method._get_yavin_orchestrator()
        with patch.object(
            orchestrator,
            "abort_payment",
            return_value={
                "operation_status": "failure",
                "error_message": "Terminal busy",
            },
        ), patch.object(
            type(self.payment_method),
            "_get_yavin_orchestrator",
            return_value=orchestrator,
        ):
            result = self.payment_method.yavin_abort_payment(payload)
        self.assertEqual(result["operation_status"], "failure")
        self.assertEqual(result["error_message"], "Terminal busy")

    def _make_reversal_payload(self, **overrides):
        """Build reversal request payload."""
        payload = {
            "payment_method_id": self.payment_method.id,
            "amount": 10.0,
            "currency_id": self.company.currency_id.id,
            "order_uid": "ORDER123",
            "payment_id": "PAY1",
            "initial_transaction_id": "TX-ORIGINAL",
        }
        payload.update(overrides)
        return payload

    def test_yavin_send_reversal_missing_currency_returns_error(self):
        """yavin_send_reversal returns error when currency_id is missing."""
        payload = self._make_reversal_payload()
        del payload["currency_id"]
        result = self.payment_method.yavin_send_reversal(payload)
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Currency", result.get("error_message", ""))

    def test_manifest_declares_only_required_pos_dependencies_and_assets(self):
        """Manifest keeps only required POS dependencies and shared frontend assets."""
        manifest_path = Path(__file__).resolve().parents[1] / "__manifest__.py"
        manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
        depends = manifest["depends"]
        pos_assets = manifest["assets"]["point_of_sale._assets_pos"]
        qunit_assets = manifest["assets"]["point_of_sale.assets_qunit_tests"]

        self.assertEqual(depends, ["point_of_sale", "pos_self_order"])
        self.assertIn(
            "pos_yavin/static/src/payment/lifecycle_utils.js",
            pos_assets,
        )
        self.assertIn(
            "pos_yavin/static/src/payment/lifecycle_utils.js",
            qunit_assets,
        )
        self.assertIn(
            "pos_yavin/static/tests/payment_yavin_polling_tests.js",
            qunit_assets,
        )

    def test_yavin_send_reversal_calls_client(self):
        """yavin_send_reversal delegates to API client."""
        payload = self._make_reversal_payload()
        orchestrator = self.payment_method._get_yavin_orchestrator()
        with patch.object(
            orchestrator,
            "send_reversal",
            return_value={"operation_status": "success"},
        ) as send_mock, patch.object(
            type(self.payment_method),
            "_get_yavin_orchestrator",
            return_value=orchestrator,
        ):
            result = self.payment_method.yavin_send_reversal(payload)
        self.assertEqual(result["operation_status"], "success")
        send_mock.assert_called_once_with(payload)

    def test_yavin_get_original_transactions_empty_refunded_returns_empty(self):
        """yavin_get_original_transactions returns [] when refunded_orderline_ids empty."""
        result = self.payment_method.yavin_get_original_transactions(
            {"refunded_orderline_ids": []}
        )
        self.assertEqual(result, [])

        result = self.payment_method.yavin_get_original_transactions({})
        self.assertEqual(result, [])

    def test_yavin_get_original_transactions_returns_yavin_payments(self):
        """yavin_get_original_transactions returns transactions from Yavin payments."""
        product = self.env["product.product"].search(
            [("sale_ok", "=", True)], limit=1
        ) or self.env["product.product"].create(
            {"name": "Test Product", "sale_ok": True, "list_price": 10.0}
        )
        pricelist = (
            self.pos_config.pricelist_id
            or self.env["product.pricelist"]
            .search([("currency_id", "=", self.company.currency_id.id)], limit=1)
            or self.env["product.pricelist"].create(
                {
                    "name": "Test Pricelist",
                    "currency_id": self.company.currency_id.id,
                }
            )
        )
        order = self.env["pos.order"].create(
            {
                "name": "Order/001",
                "session_id": self.pos_session.id,
                "company_id": self.company.id,
                "amount_tax": 0.0,
                "amount_total": 10.0,
                "amount_paid": 10.0,
                "amount_return": 0.0,
                "pricelist_id": pricelist.id,
            }
        )
        line = self.env["pos.order.line"].create(
            {
                "order_id": order.id,
                "product_id": product.id,
                "qty": 1,
                "price_unit": 10.0,
                "price_subtotal": 10.0,
                "price_subtotal_incl": 10.0,
            }
        )
        self.env["pos.payment"].create(
            {
                "name": "PAY001",
                "pos_order_id": order.id,
                "payment_method_id": self.payment_method.id,
                "amount": 10.0,
                "payment_date": fields.Datetime.now(),
                "transaction_id": "TX-YAVIN-123",
                "payment_status": "done",
            }
        )

        result = self.payment_method.yavin_get_original_transactions(
            {"refunded_orderline_ids": [line.id]}
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["transaction_id"], "TX-YAVIN-123")
        self.assertEqual(result[0]["amount"], 10.0)

    def test_check_yavin_allows_missing_ip_address_until_payment(self):
        """Local terminal address may be empty so discovery can fill it later."""
        method = self.env["pos.payment.method"].create(
            {
                "name": "Yavin Method Pending Address",
                "company_id": self.company.id,
                "journal_id": self.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "local",
            }
        )
        self.assertFalse(method.yavin_ip_address)

    def test_is_write_forbidden_allows_yavin_configuration_fields(self):
        self.assertFalse(
            self.payment_method._is_write_forbidden({"yavin_ip_address"}),
            "Yavin IP updates should remain allowed with open sessions",
        )
        self.assertFalse(
            self.payment_method._is_write_forbidden({"yavin_display_tip"}),
            "Display tip updates should remain allowed with open sessions",
        )
        self.assertFalse(
            self.payment_method._is_write_forbidden({"yavin_connection_mode"}),
        )
        self.assertFalse(
            self.payment_method._is_write_forbidden({"yavin_terminal_serial", "yavin_cloud_api_key"}),
        )

    def test_is_write_forbidden_keeps_standard_restrictions_for_other_fields(self):
        self.assertTrue(self.payment_method.open_session_ids)
        self.assertTrue(self.payment_method._is_write_forbidden({"name"}))

    def test_cloud_api_key_field_is_restricted_to_pos_managers(self):
        cloud_key_field = self.env["pos.payment.method"]._fields["yavin_cloud_api_key"]
        self.assertEqual(cloud_key_field.groups, "point_of_sale.group_pos_manager")

    def test_cloud_api_key_view_is_readable_and_group_restricted(self):
        view = self.env.ref("pos_yavin.pos_payment_method_view_form_inherit_yavin")
        self.assertIn('name="yavin_cloud_api_key"', view.arch_db)
        self.assertIn('groups="point_of_sale.group_pos_manager"', view.arch_db)
        self.assertNotIn('password="True"', view.arch_db)

    def test_yavin_discover_terminals_action_opens_wizard(self):
        action = self.payment_method.yavin_discover_terminals_action()

        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["res_model"], "yavin.discover.wizard")
        self.assertEqual(action["target"], "new")

    def test_yavin_discover_terminals_action_rejects_non_yavin_methods(self):
        other_method = self.env["pos.payment.method"].create(
            {
                "name": "Manual Method",
                "company_id": self.company.id,
                "journal_id": self.bank_journal.id,
            }
        )

        action = other_method.yavin_discover_terminals_action()

        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(action["params"]["type"], "danger")
