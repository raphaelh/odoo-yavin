"""Operation flow handlers for Yavin payment API."""
# pylint: disable=too-many-locals

import json
import logging
import time

import requests
from odoo import _

from ..constants import (
    YAVIN_ABORT_TIMEOUT_SEC,
    YAVIN_API_ABORT_ENDPOINT,
    YAVIN_API_PAYMENT_ENDPOINT,
    YAVIN_API_REVERSAL_ENDPOINT,
    YAVIN_DEFAULT_TIMEOUT_MS,
    YAVIN_RESPONSE_WAIT_TIME_MS,
    YAVIN_REVERSAL_TIMEOUT_MS,
)
from ..responses import build_operation_response

logger = logging.getLogger(__name__)


class YavinOperationHandlers:
    """Handle payment, abort, and reversal operation flows."""

    def __init__(self, ip_address, base_url, dependencies):
        """Initialize operation handlers with shared dependencies."""
        self.ip_address = ip_address
        self.base_url = base_url
        self.transport = dependencies["transport"]
        self.amount_converter = dependencies["amount_converter"]
        self.payload_builder = dependencies["payload_builder"]
        self.response_parser = dependencies["response_parser"]

    @staticmethod
    def is_payment_response(response_data):
        """Return True when payload has payment response shape."""
        return "amount" in response_data

    def wait_for_second_response(self, wait_time_ms=None):
        """Wait for potential second response in race conditions."""
        if wait_time_ms is None:
            wait_time_ms = YAVIN_RESPONSE_WAIT_TIME_MS
        time.sleep(wait_time_ms / 1000.0)

    def send_payment(self, data, amount, currency):
        """Execute payment request flow and map errors."""
        order_uid = data.get("order_uid") or ""
        payment_id = data.get("payment_id") or ""
        if not order_uid:
            return build_operation_response(
                "issue",
                error_message=_(
                    "Order UID is missing. Cannot process payment without order identification."
                ),
            )
        if not payment_id:
            return build_operation_response(
                "issue",
                error_message=_(
                    "Payment line ID is missing. Cannot process payment without payment line."
                ),
            )

        amount_cent = self.amount_converter.convert_amount_to_cents(amount, currency)
        payload = self.payload_builder.build_payment_payload(data, amount_cent, currency)
        url = f"{self.base_url}{YAVIN_API_PAYMENT_ENDPOINT}"
        timeout_sec = data.get("timeout", YAVIN_DEFAULT_TIMEOUT_MS) / 1000
        logger.info(
            "Sending payment request to Yavin terminal %s: %s %s cents, idempotentUuid=%s",
            self.ip_address,
            currency.name,
            amount_cent,
            payload.get("idempotentUuid"),
        )
        try:
            response_data = self.transport.post_json(url, payload, timeout_sec)
            logger.debug(
                "Payment response from Yavin terminal %s:\n%s",
                self.ip_address,
                json.dumps(response_data, indent=2),
            )
            if not self.is_payment_response(response_data):
                logger.warning(
                    "Received abort response from payment endpoint (non-deterministic order). "
                    "Waiting for payment response..."
                )
                self.wait_for_second_response()
                return build_operation_response(
                    "failure",
                    error_message=_(
                        "Payment was aborted. The abort response arrived before the payment."
                    ),
                )

            sent_uuid = payload.get("idempotentUuid")
            received_uuid = response_data.get("idempotentUuid")
            if sent_uuid and received_uuid and sent_uuid != received_uuid:
                error_msg = _(
                    "IdempotentUuid mismatch! Sent: %(sent)s, Received: %(received)s. "
                    "Ignoring response as it belongs to another request.",
                    sent=sent_uuid,
                    received=received_uuid,
                )
                logger.warning(error_msg)
                return build_operation_response(
                    "issue", error_message=error_msg, retryable=True
                )

            return self.response_parser.parse_payment_response(response_data, currency)
        except (requests.exceptions.RequestException, ValueError) as exc:
            return self.transport.handle_http_exception(exc, operation="communicating")

    def abort_payment(self, order_uid, payment_id, attempt_num=1, wait_for_payment=True):
        """Execute abort request flow and map errors."""
        if not order_uid:
            return build_operation_response(
                "issue",
                error_message=_(
                    "Order UID is missing. Cannot abort payment without identification."
                ),
            )
        if not payment_id:
            return build_operation_response(
                "issue",
                error_message=_(
                    "Payment line ID is missing. Cannot abort payment without identification."
                ),
            )

        payload = self.payload_builder.build_abort_payload(order_uid, payment_id, attempt_num)
        url = f"{self.base_url}{YAVIN_API_ABORT_ENDPOINT}"
        logger.info("Aborting payment on Yavin terminal %s", self.ip_address)
        try:
            response_data = self.transport.post_json(url, payload, YAVIN_ABORT_TIMEOUT_SEC)
            logger.debug(
                "Abort response from Yavin terminal %s:\n%s",
                self.ip_address,
                json.dumps(response_data, indent=2),
            )
            if self.is_payment_response(response_data):
                logger.warning(
                    "Received payment response from abort endpoint (non-deterministic order). "
                    "Waiting for abort response..."
                )
                if wait_for_payment:
                    self.wait_for_second_response()
                return build_operation_response(
                    "issue",
                    error_message=_(
                        "Received payment response instead of abort response. "
                        "The payment may have completed before abort could be processed."
                    ),
                    payment_response_received=True,
                )

            status = response_data.get("status", "")
            if status == "ok":
                logger.info("Payment aborted successfully on Yavin terminal %s", self.ip_address)
                if wait_for_payment:
                    self.wait_for_second_response()
                return build_operation_response("success")

            error_message = response_data.get("message", _("Failed to abort payment"))
            logger.warning(
                "Payment abort failed on Yavin terminal %s: %s",
                self.ip_address,
                error_message,
            )
            return build_operation_response("failure", error_message=error_message)
        except (requests.exceptions.RequestException, ValueError) as exc:
            return self.transport.handle_http_exception(exc, operation="aborting")

    def send_reversal(self, data, amount, currency):
        """Execute reversal request flow and map errors."""
        order_uid = data.get("order_uid") or ""
        payment_id = data.get("payment_id") or ""
        initial_tx_id = data.get("initial_transaction_id") or ""
        if not order_uid:
            return build_operation_response(
                "issue",
                error_message=_("Order UID is missing. Cannot process reversal without ID."),
            )
        if not payment_id:
            return build_operation_response(
                "issue",
                error_message=_("Payment line ID is missing. Cannot process reversal without ID."),
            )
        if not initial_tx_id:
            return build_operation_response(
                "issue",
                error_message=_(
                    "Initial transaction ID is missing. Cannot process reversal."
                ),
            )

        amount_cent = self.amount_converter.convert_amount_to_cents(amount, currency)
        payload = self.payload_builder.build_reversal_payload(
            amount_cent, initial_tx_id, order_uid, payment_id, data.get("attempt_number", 1)
        )
        url = f"{self.base_url}{YAVIN_API_REVERSAL_ENDPOINT}"
        timeout_sec = data.get("timeout", YAVIN_REVERSAL_TIMEOUT_MS) / 1000
        logger.info(
            "Sending reversal request to Yavin terminal %s: %s %s cents, "
            "initial_tx_id=%s, idempotentUuid=%s",
            self.ip_address,
            currency.name,
            amount_cent,
            initial_tx_id,
            payload.get("idempotentUuid"),
        )
        try:
            response_data = self.transport.post_json(url, payload, timeout_sec)
            logger.debug(
                "Reversal response from Yavin terminal %s:\n%s",
                self.ip_address,
                json.dumps(response_data, indent=2),
            )
            return self.response_parser.parse_reversal_response(response_data)
        except requests.exceptions.HTTPError as exc:
            response_status = "unknown"
            response_text = "no response"
            try:
                if hasattr(exc, "response") and exc.response:
                    response_status = exc.response.status_code
                    response_text = exc.response.text or "no text"
            except Exception as nested_error:  # pylint: disable=broad-exception-caught
                logger.debug("Could not read HTTP error response details: %s", nested_error)
            logger.warning(
                "Yavin reversal HTTP error on %s (status=%s): %s; response=%s",
                self.ip_address,
                response_status,
                str(exc),
                (
                    response_text[:500]
                    if response_text and len(response_text) > 500
                    else response_text
                ),
            )
            return self.transport.handle_http_exception(exc, operation="reversing")
        except (requests.exceptions.RequestException, ValueError) as exc:
            return self.transport.handle_http_exception(exc, operation="reversing")
