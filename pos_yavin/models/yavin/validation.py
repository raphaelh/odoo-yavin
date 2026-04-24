"""Validation services for Yavin payment terminal."""

import logging

from odoo import _
from odoo.exceptions import ValidationError

from .constants import SUPPORTED_CURRENCIES
from .network.address_resolver import YavinAddressResolver
from .responses import build_operation_response
from .secrets import is_valid_cloud_api_key, normalize_secret

logger = logging.getLogger(__name__)


class YavinPaymentValidator:
    """Validator for Yavin payment requests."""

    def __init__(self, env):
        """
        Initialize the validator.

        :param env: Odoo environment
        """
        self.env = env

    def create_error_response(self, message):
        """
        Create standardized error response.

        :param message: Error message
        :return: Dictionary with error response
        """
        return build_operation_response(
            "issue",
            error_message=message,
        )

    def validate_payment_method(self, data):
        """
        Validate payment method from data and return it.

        :param data: Dictionary with payment_method_id
        :return: Tuple (payment_method, error_response) where error_response is None if valid
        """
        payment_method_id = data.get("payment_method_id")
        if not payment_method_id:
            error_msg = _("Payment method ID is missing in request.")
            logger.error("Payment method ID missing in request")
            return None, self.create_error_response(error_msg)

        payment_method = self.env["pos.payment.method"].browse(payment_method_id).exists()
        if not payment_method:
            error_msg = _("Payment method %(id)s not found.", id=payment_method_id)
            logger.error(error_msg)
            return None, self.create_error_response(error_msg)
        return payment_method, None

    def resolve_ip_address(self, payment_method, operation="payment"):
        """
        Validate and resolve IP address for payment method with logging.

        :param payment_method: Payment method record
        :param operation: Operation name for logging ("payment" or "abort")
        :return: Tuple (resolved_ip, error_response) where error_response is None if valid
        """
        ip_addr = payment_method.yavin_ip_address
        if not ip_addr:
            error_msg = _(
                "Yavin payment terminal IP address is not set on payment method '%(method)s'. "
                "Please configure it in Point of Sale > Configuration > Payment Methods.",
                method=payment_method.display_name,
            )
            logger.error("Yavin IP address not configured for payment method %s", payment_method.id)
            return None, self.create_error_response(error_msg)

        logger.debug(
            "Resolving address for %s method %s: '%s'",
            operation,
            payment_method.id,
            ip_addr
        )
        try:
            # Use YavinAddressResolver directly to respect SRP (logic is in network package)
            resolved_ip = YavinAddressResolver(self.env).resolve_address(ip_addr)
            if resolved_ip != ip_addr:
                logger.debug(
                    "Resolved Bonjour name '%s' to IP address '%s' for %s method %s",
                    ip_addr,
                    resolved_ip,
                    operation,
                    payment_method.id
                )
            else:
                logger.debug(
                    "Using IP address '%s' directly for %s method %s",
                    ip_addr,
                    operation,
                    payment_method.id
                )
            return resolved_ip, None
        except ValidationError as e:
            logger.error(
                "Failed to resolve address '%s' for %s method %s: %s",
                ip_addr,
                operation,
                payment_method.id,
                str(e)
            )
            return None, self.create_error_response(str(e))

    def validate_cloud_credentials(self, payment_method):
        """
        Validate serial number and API key for Cloud mode.

        :return: Tuple ``(tuple(serial, api_key), error_response)`` with error None if ok.
        """
        if payment_method.yavin_effective_connection_mode != "cloud":
            return None, self.create_error_response(
                _("Payment method is not configured for Yavin Cloud API."),
            )
        serial = normalize_secret(payment_method.yavin_terminal_serial)
        api_key = normalize_secret(payment_method.yavin_cloud_api_key)
        if not serial:
            return None, self.create_error_response(
                _(
                    "Yavin terminal serial number is not set on payment method '%(method)s'.",
                    method=payment_method.display_name,
                ),
            )
        if not api_key:
            return None, self.create_error_response(
                _(
                    "Yavin Cloud API key is not set on payment method '%(method)s'.",
                    method=payment_method.display_name,
                ),
            )
        if not is_valid_cloud_api_key(api_key):
            return None, self.create_error_response(
                _(
                    "Yavin Cloud API key is invalid on payment method '%(method)s'. "
                    "Use the real key from Yavin Services.",
                    method=payment_method.display_name,
                )
            )
        return (serial, api_key), None

    def validate_currency(self, currency):
        """
        Validate that the currency is supported by Yavin.
        
        :param currency: Currency record
        :raises ValidationError: If currency is not supported
        """
        if currency.name not in SUPPORTED_CURRENCIES:
            raise ValidationError(
                _(
                    "Currency %(currency)s is not supported by Yavin. "
                    "Supported currencies are: %(supported)s",
                    currency=currency.name,
                    supported=", ".join(SUPPORTED_CURRENCIES),
                )
            )

    def validate_amount(self, amount, currency, operation="payment"):
        """
        Validate the amount for a Yavin operation.
        
        :param amount: Amount to validate
        :param currency: Currency record
        :param operation: Operation name, used for payment-specific rules
        :return: Error response or None if valid
        """
        if not currency.compare_amounts(amount, 0):
            logger.error("Amount for payment terminal is 0")
            return self.create_error_response(
                _("You are trying to send a null amount to the payment terminal!")
            )

        if operation == "payment" and amount < 0:
            logger.error("Amount for payment terminal is negative: %s", amount)
            error_msg = _(
                "Cannot process negative amount (refund) without original transaction "
                "reference. Please use the refund feature on the original order."
            )
            return self.create_error_response(error_msg)

        return None
