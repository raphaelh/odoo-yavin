"""Application orchestrator for Yavin payment operations."""

from odoo import _
from odoo.exceptions import ValidationError

from ..api.client import YavinAPIClient
from .cloud_payment import YavinCloudPaymentService
from ..formatting.data_extractor import YavinDataExtractor
from ..validation import YavinPaymentValidator


class YavinPaymentOrchestrator:
    """Orchestrate validation, enrichment, and API client calls."""

    def __init__(self, env):
        self.env = env
        self.validator = YavinPaymentValidator(env)
        self.extractor = YavinDataExtractor(env)

    def _validate_currency(self, data, missing_message):
        """Validate currency payload and return `(currency, error_response)`."""
        currency_id = data.get("currency_id")
        if not currency_id:
            return None, self.validator.create_error_response(_(missing_message))
        currency = self.env["res.currency"].browse(currency_id)
        try:
            self.validator.validate_currency(currency)
        except ValidationError as exc:
            return None, self.validator.create_error_response(str(exc))
        return currency, None

    def _build_local_client(self, payment_method, operation):
        """Resolve local terminal address and build the LAN API client."""
        resolved_ip, error = self.validator.resolve_ip_address(
            payment_method, operation=operation
        )
        if error:
            return None, None, error
        return payment_method, YavinAPIClient(resolved_ip, self.env), None

    def start_payment(self, data):
        """Validate and start a Cloud payment (POS polls ``yavin_cloud_status``)."""
        payment_method, error = self.validator.validate_payment_method(data)
        if error:
            return error

        if payment_method.yavin_effective_connection_mode != "cloud":
            return self.validator.create_error_response(
                _("Yavin Cloud start is only available when the payment method uses Cloud API."),
            )

        currency, error = self._validate_currency(
            data, "Currency ID is missing in payment request."
        )
        if error:
            return error

        amount = data.get("amount")
        error = self.validator.validate_amount(amount, currency, operation="payment")
        if error:
            return error

        cloud = YavinCloudPaymentService(self.env)
        return cloud.start_payment(
            payment_method, data, amount, currency, self.validator, self.extractor
        )

    def cloud_status(self, data):
        """Read or expire a Cloud transaction row (short RPC)."""
        payment_method, error = self.validator.validate_payment_method(data)
        if error:
            return error

        if payment_method.yavin_effective_connection_mode != "cloud":
            return self.validator.create_error_response(
                _("Yavin Cloud status is only available when the payment method uses Cloud API."),
            )

        tx_id = data.get("yavin_tx_id")
        if tx_id is None:
            return self.validator.create_error_response(
                _("Missing cloud transaction reference."),
            )
        try:
            tx_id = int(tx_id)
        except (TypeError, ValueError):
            return self.validator.create_error_response(
                _("Invalid cloud transaction reference."),
            )

        cloud = YavinCloudPaymentService(self.env)
        if data.get("expire"):
            return cloud.expire_if_pending(payment_method, tx_id)
        return cloud.read_status(payment_method, tx_id)

    def send_payment(self, data):
        """Validate, enrich, and send payment request."""
        payment_method, error = self.validator.validate_payment_method(data)
        if error:
            return error

        currency, error = self._validate_currency(
            data, "Currency ID is missing in payment request."
        )
        if error:
            return error

        amount = data.get("amount")
        error = self.validator.validate_amount(amount, currency, operation="payment")
        if error:
            return error

        if payment_method.yavin_effective_connection_mode == "cloud":
            return self.start_payment(data)

        _pm, client, err = self._build_local_client(payment_method, "payment")
        if err:
            return err

        customer_data = self.extractor.extract_customer_data(data.get("partner_id"))
        cashier_name = data.get("cashier_name") or self.extractor.extract_cashier_name(
            data.get("session_id")
        )
        enriched_data = data.copy()
        enriched_data["customer"] = customer_data
        enriched_data["cashier_name"] = cashier_name
        return client.send_payment(enriched_data, amount, currency)

    def abort_payment(self, data):
        """Validate and send abort request."""
        payment_method, error = self.validator.validate_payment_method(data)
        if error:
            return error
        if payment_method.yavin_effective_connection_mode == "cloud":
            cloud = YavinCloudPaymentService(self.env)
            return cloud.abort_payment(
                payment_method,
                data.get("order_uid") or "",
                data.get("payment_id") or "",
                data.get("attempt_number", 1),
                self.validator,
            )
        _pm, client, err = self._build_local_client(payment_method, "abort")
        if err:
            return err
        return client.abort_payment(
            data.get("order_uid") or "",
            data.get("payment_id") or "",
            data.get("attempt_number", 1),
            wait_for_payment=True,
        )

    def send_reversal(self, data):
        """Validate and send reversal request."""
        payment_method, error = self.validator.validate_payment_method(data)
        if error:
            return error

        currency, error = self._validate_currency(
            data, "Currency ID is missing in reversal request."
        )
        if error:
            return error

        amount = data.get("amount")
        error = self.validator.validate_amount(amount, currency, operation="reversal")
        if error:
            return error

        if payment_method.yavin_effective_connection_mode == "cloud":
            cloud = YavinCloudPaymentService(self.env)
            return cloud.send_reversal(
                payment_method, data, amount, currency, self.validator
            )

        _pm, client, err = self._build_local_client(payment_method, "reversal")
        if err:
            return err
        return client.send_reversal(data, amount, currency)
