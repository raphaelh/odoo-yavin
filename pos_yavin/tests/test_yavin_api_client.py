# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for :class:`YavinAPIClient`."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,protected-access,too-many-public-methods,too-few-public-methods,missing-class-docstring

from unittest.mock import patch

import requests

from odoo.tests.common import TransactionCase

from odoo.addons.pos_yavin.models.yavin.api.client import YavinAPIClient


class TestYavinAPIClient(TransactionCase):
    """Test suite for YavinAPIClient."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        eur = cls.env.ref("base.EUR")
        cls.company = cls.env["res.company"].create(
            {
                "name": "Yavin API Test",
                "currency_id": eur.id,
            }
        )
        cls.env.user.company_ids |= cls.company
        cls.env.user.company_id = cls.company

    def _make_client(self, ip="127.0.0.1"):
        """Create a YavinAPIClient instance."""
        return YavinAPIClient(ip, self.env)

    def _make_payment_data(self, **overrides):
        """Build payment request data."""
        data = {
            "payment_method_id": 1,
            "amount": 10.0,
            "currency_id": self.company.currency_id.id,
            "payment_id": "PAY1",
            "order_uid": "ORDER1",
            "timeout": 5000,
        }
        data.update(overrides)
        return data

    def test_send_payment_missing_order_uid_returns_error(self):
        """send_payment returns error when order_uid is missing."""
        client = self._make_client()
        data = self._make_payment_data(order_uid="")
        amount = 10.0
        currency = self.company.currency_id

        result = client.send_payment(data, amount, currency)

        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Order UID", result["error_message"])

    def test_send_payment_missing_payment_id_returns_error(self):
        """send_payment returns error when payment_id is missing."""
        client = self._make_client()
        data = self._make_payment_data(payment_id="")
        amount = 10.0
        currency = self.company.currency_id

        result = client.send_payment(data, amount, currency)

        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Payment line ID", result["error_message"])

    def test_send_payment_success(self):
        """send_payment returns success when API responds ok."""
        client = self._make_client()
        data = self._make_payment_data()
        amount = 10.0
        currency = self.company.currency_id

        mock_response = {
            "status": "ok",
            "amount": 1000,
            "transactionId": "TX123",
            "scheme": "VISA",
            "issuer": "Test Bank",
        }

        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = mock_response
            mock_post.return_value.raise_for_status = lambda: None

            result = client.send_payment(data, amount, currency)

        self.assertEqual(result["operation_status"], "success")
        self.assertEqual(result["transaction_id"], "TX123")
        self.assertEqual(result["card_type"], "VISA")

    def test_send_payment_timeout_returns_error(self):
        """send_payment returns error on timeout."""
        client = self._make_client()
        data = self._make_payment_data()
        amount = 10.0
        currency = self.company.currency_id

        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")

            result = client.send_payment(data, amount, currency)

        self.assertEqual(result["operation_status"], "timeout")
        self.assertIn("timed out", result["error_message"])

    def test_abort_payment_missing_order_uid_returns_error(self):
        """abort_payment returns error when order_uid is missing."""
        client = self._make_client()
        result = client.abort_payment("", "PAY1")
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Order UID", result["error_message"])

    def test_abort_payment_success(self):
        """abort_payment returns success when API responds ok."""
        client = self._make_client()
        mock_response = {"status": "ok"}

        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = mock_response
            mock_post.return_value.raise_for_status = lambda: None

            result = client.abort_payment("ORDER1", "PAY1")

        self.assertEqual(result["operation_status"], "success")

    def test_send_reversal_missing_initial_transaction_id_returns_error(self):
        """send_reversal returns error when initial_transaction_id is missing."""
        client = self._make_client()
        data = {
            "order_uid": "ORDER1",
            "payment_id": "PAY1",
            "initial_transaction_id": "",
            "currency_id": self.company.currency_id.id,
            "amount": 10.0,
        }
        amount = 10.0
        currency = self.company.currency_id

        result = client.send_reversal(data, amount, currency)

        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Initial transaction ID", result["error_message"])

    def test_send_reversal_success(self):
        """send_reversal returns success when API responds ok."""
        client = self._make_client()
        data = {
            "order_uid": "ORDER1",
            "payment_id": "PAY1",
            "initial_transaction_id": "TX123",
            "currency_id": self.company.currency_id.id,
            "amount": 10.0,
        }
        amount = 10.0
        currency = self.company.currency_id

        mock_response = {"status": "ok"}

        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = mock_response
            mock_post.return_value.raise_for_status = lambda: None

            result = client.send_reversal(data, amount, currency)

        self.assertEqual(result["operation_status"], "success")
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        self.assertEqual(payload["vendor"]["softwareName"], "Odoo POS")
        self.assertTrue(payload["vendor"]["softwareVersion"])

    def test_send_payment_uses_attempt_number_in_idempotent_uuid(self):
        """Payment payload includes attempt_number in idempotentUuid for retry after failure."""
        client = self._make_client()
        data = self._make_payment_data(attempt_number=2)
        amount = 10.0
        currency = self.company.currency_id

        mock_response = {
            "status": "ok",
            "amount": 1000,
            "transactionId": "TX456",
            "scheme": "CB",
            "issuer": "Test Bank",
        }

        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = mock_response
            mock_post.return_value.raise_for_status = lambda: None

            result = client.send_payment(data, amount, currency)

        self.assertEqual(result["operation_status"], "success")
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        self.assertEqual(
            payload["idempotentUuid"],
            "ORDER1-PAY1-2",
            "idempotentUuid must include attempt_number for retry after failure (ko)",
        )

    def test_send_payment_connection_error_dns_resolution(self):
        client = self._make_client()
        data = self._make_payment_data()
        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError("Failed to resolve host")
            result = client.send_payment(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "network_error")
        self.assertIn("resolve terminal address", result["error_message"])

    def test_send_payment_connection_error_refused(self):
        client = self._make_client()
        data = self._make_payment_data()
        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")
            result = client.send_payment(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "network_error")
        self.assertIn("refused", result["error_message"])

    def test_send_payment_connection_error_unreachable(self):
        client = self._make_client()
        data = self._make_payment_data()
        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError("Network is unreachable")
            result = client.send_payment(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "network_error")
        self.assertIn("Network unreachable", result["error_type"])

    def test_send_payment_connection_error_generic(self):
        client = self._make_client()
        data = self._make_payment_data()
        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError("socket reset")
            result = client.send_payment(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "network_error")
        self.assertIn("Cannot connect", result["error_message"])

    def test_send_payment_http_error_returns_issue(self):
        client = self._make_client()
        data = self._make_payment_data()
        response = requests.Response()
        response.status_code = 500
        response._content = b'{"status":"ko"}'
        http_error = requests.exceptions.HTTPError("Server error")
        http_error.response = response
        with patch("requests.post") as mock_post:
            mock_post.return_value.raise_for_status.side_effect = http_error
            mock_post.return_value.json.return_value = {"status": "ko"}
            result = client.send_payment(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("HTTP error", result["error_message"])

    def test_handle_http_exception_http_error_with_unreadable_response_body(self):
        client = self._make_client()

        class BrokenResponse:
            status_code = 500

            @property
            def text(self):
                raise RuntimeError("cannot read body")

        http_error = requests.exceptions.HTTPError("Server error")
        http_error.response = BrokenResponse()
        result = client._handle_http_exception(http_error, operation="communicating")
        self.assertEqual(result["operation_status"], "issue")

    def test_handle_http_exception_http_error_with_unserializable_response_object(self):
        client = self._make_client()

        class BrokenResponse:
            status_code = 500

            @property
            def text(self):
                raise RuntimeError("cannot read body")

            def __getattribute__(self, name):
                if name == "__dict__":
                    raise RuntimeError("cannot serialize response object")
                return super().__getattribute__(name)

        http_error = requests.exceptions.HTTPError("Server error")
        http_error.response = BrokenResponse()
        result = client._handle_http_exception(http_error, operation="communicating")
        self.assertEqual(result["operation_status"], "issue")

    def test_handle_http_exception_request_exception_branch(self):
        client = self._make_client()
        result = client._handle_http_exception(
            requests.exceptions.RequestException("request failed"),
            operation="communicating",
        )
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("request failed", result["error_message"])

    def test_handle_http_exception_unexpected_exception_branch(self):
        client = self._make_client()
        result = client._handle_http_exception(
            RuntimeError("unexpected"),
            operation="communicating",
        )
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Unexpected error", result["error_message"])

    def test_send_payment_abort_response_returns_failure(self):
        client = self._make_client()
        data = self._make_payment_data()
        with patch("requests.post") as mock_post:
            mock_post.return_value.raise_for_status = lambda: None
            # No amount key => abort response shape
            mock_post.return_value.json.return_value = {"status": "ok"}
            result = client.send_payment(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "failure")
        self.assertIn("aborted", result["error_message"].lower())

    def test_send_payment_idempotent_uuid_mismatch_returns_issue(self):
        client = self._make_client()
        data = self._make_payment_data()
        with patch("requests.post") as mock_post:
            mock_post.return_value.raise_for_status = lambda: None
            mock_post.return_value.json.return_value = {
                "status": "ok",
                "amount": 1000,
                "transactionId": "TX-777",
                "idempotentUuid": "ORDER1-PAY1-999",
            }
            result = client.send_payment(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("IdempotentUuid mismatch", result["error_message"])

    def test_abort_payment_missing_payment_id_returns_error(self):
        client = self._make_client()
        result = client.abort_payment("ORDER1", "")
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Payment line ID", result["error_message"])

    def test_abort_payment_receives_payment_response_marks_issue(self):
        client = self._make_client()
        with patch("requests.post") as mock_post, patch.object(
            client.handlers, "wait_for_second_response"
        ) as wait_mock:
            mock_post.return_value.raise_for_status = lambda: None
            mock_post.return_value.json.return_value = {"amount": 1000, "status": "ok"}
            result = client.abort_payment("ORDER1", "PAY1", wait_for_payment=False)
        self.assertEqual(result["operation_status"], "issue")
        self.assertTrue(result.get("payment_response_received"))
        wait_mock.assert_not_called()

    def test_abort_payment_receives_payment_response_waits_when_enabled(self):
        client = self._make_client()
        with patch("requests.post") as mock_post, patch.object(
            client.handlers, "wait_for_second_response"
        ) as wait_mock:
            mock_post.return_value.raise_for_status = lambda: None
            mock_post.return_value.json.return_value = {"amount": 1000, "status": "ok"}
            result = client.abort_payment("ORDER1", "PAY1", wait_for_payment=True)
        self.assertEqual(result["operation_status"], "issue")
        wait_mock.assert_called_once()

    def test_abort_payment_failure_without_message_uses_default(self):
        client = self._make_client()
        with patch("requests.post") as mock_post:
            mock_post.return_value.raise_for_status = lambda: None
            mock_post.return_value.json.return_value = {"status": "ko"}
            result = client.abort_payment("ORDER1", "PAY1")
        self.assertEqual(result["operation_status"], "failure")
        self.assertIn("Failed to abort payment", result["error_message"])

    def test_abort_payment_request_exception_returns_issue(self):
        client = self._make_client()
        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.RequestException("network down")
            result = client.abort_payment("ORDER1", "PAY1")
        self.assertEqual(result["operation_status"], "issue")

    def test_send_reversal_http_error_branch_returns_issue(self):
        client = self._make_client()
        data = {
            "order_uid": "ORDER1",
            "payment_id": "PAY1",
            "initial_transaction_id": "TX123",
            "currency_id": self.company.currency_id.id,
            "amount": 10.0,
        }
        response = requests.Response()
        response.status_code = 502
        response._content = b"gateway error"
        http_error = requests.exceptions.HTTPError("Bad gateway")
        http_error.response = response
        with patch("requests.post") as mock_post:
            mock_post.return_value.raise_for_status.side_effect = http_error
            result = client.send_reversal(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("HTTP error", result["error_message"])

    def test_send_reversal_http_error_with_unreadable_response_details(self):
        client = self._make_client()
        data = {
            "order_uid": "ORDER1",
            "payment_id": "PAY1",
            "initial_transaction_id": "TX123",
        }

        class BrokenResponse:
            def __bool__(self):
                return True

            status_code = 502

            @property
            def text(self):
                raise RuntimeError("cannot read body")

        http_error = requests.exceptions.HTTPError("Bad gateway")
        http_error.response = BrokenResponse()
        with patch("requests.post") as mock_post:
            mock_post.return_value.raise_for_status.side_effect = http_error
            result = client.send_reversal(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "issue")

    def test_send_reversal_missing_order_uid_returns_issue(self):
        client = self._make_client()
        data = {"order_uid": "", "payment_id": "PAY1", "initial_transaction_id": "TX123"}
        result = client.send_reversal(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Order UID", result["error_message"])

    def test_send_reversal_missing_payment_id_returns_issue(self):
        client = self._make_client()
        data = {"order_uid": "ORDER1", "payment_id": "", "initial_transaction_id": "TX123"}
        result = client.send_reversal(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Payment line ID", result["error_message"])

    def test_send_reversal_value_error_returns_issue(self):
        client = self._make_client()
        data = {
            "order_uid": "ORDER1",
            "payment_id": "PAY1",
            "initial_transaction_id": "TX123",
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value.raise_for_status = lambda: None
            mock_post.return_value.json.side_effect = ValueError("bad json")
            result = client.send_reversal(data, 10.0, self.company.currency_id)
        self.assertEqual(result["operation_status"], "issue")
