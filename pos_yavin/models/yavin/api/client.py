# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Yavin API public entrypoint."""

from ..constants import YAVIN_API_PORT
from ..formatting.amount_converter import YavinAmountConverter
from ..version.provider import YavinVersionProvider
from .http_transport import YavinHttpTransport
from .operation_handlers import YavinOperationHandlers
from .payload_builder import YavinPayloadBuilder
from .response_parser import YavinResponseParser


class YavinAPIClient:
    """Public facade for Yavin payment terminal communication."""
    # pylint: disable=too-many-instance-attributes

    def __init__(self, ip_address, env):
        """
        Initialize the Yavin API client.

        :param ip_address: IP address or DNS name of the Yavin payment terminal
        :param env: Odoo environment
        """
        self.ip_address = ip_address
        self.env = env
        self.base_url = f"http://{ip_address}:{YAVIN_API_PORT}"
        self.version_provider = YavinVersionProvider()
        self.amount_converter = YavinAmountConverter()
        self.payload_builder = YavinPayloadBuilder(self.version_provider)
        self.response_parser = YavinResponseParser(self.amount_converter, self.env)
        self.transport = YavinHttpTransport(self.ip_address)
        self.handlers = YavinOperationHandlers(
            self.ip_address,
            self.base_url,
            {
                "transport": self.transport,
                "amount_converter": self.amount_converter,
                "payload_builder": self.payload_builder,
                "response_parser": self.response_parser,
            },
        )

    def _handle_http_exception(self, exception, operation="communicating"):
        return self.transport.handle_http_exception(exception, operation=operation)

    def send_payment(self, data, amount, currency):
        """
        Send a payment request to the Yavin terminal.

        :param data: Dictionary containing payment data from frontend
        :param amount: Payment amount
        :param currency: Currency record
        :return: Dictionary with operation_status and response data
        """
        return self.handlers.send_payment(data, amount, currency)

    def _is_payment_response(self, response_data):
        """
        Check if a response is a payment response (contains 'amount' field).

        :param response_data: JSON response data from API
        :return: True if payment response, False if abort response
        """
        return self.handlers.is_payment_response(response_data)

    def _wait_for_second_response(self, wait_time_ms=None):
        """
        Wait for potential second response when payment and abort are sent simultaneously.

        :param wait_time_ms: Time to wait in milliseconds (default: YAVIN_RESPONSE_WAIT_TIME_MS)
        """
        self.handlers.wait_for_second_response(wait_time_ms=wait_time_ms)

    def abort_payment(self, order_uid, payment_id, attempt_num=1, wait_for_payment=True):
        """
        Abort a payment transaction on the Yavin terminal.

        :param order_uid: Order UID from frontend
        :param payment_id: Payment ID from frontend
        :param attempt_num: Attempt number for idempotentUuid (default: 1)
        :param wait_for_payment: Whether to wait for payment response after abort
        :return: Dictionary with operation_status for the abort request
        """
        return self.handlers.abort_payment(order_uid, payment_id, attempt_num, wait_for_payment)

    def send_reversal(self, data, amount, currency):
        """
        Send a reversal request to the Yavin terminal.

        :param data: Dictionary containing reversal data from frontend
        :param amount: Reversal amount
        :param currency: Currency record
        :return: Dictionary with operation_status and response data
        """
        return self.handlers.send_reversal(data, amount, currency)
