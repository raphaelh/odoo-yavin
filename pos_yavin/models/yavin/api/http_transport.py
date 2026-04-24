"""HTTP transport and exception handling for Yavin API calls."""

import logging

import requests
from odoo import _

from ..constants import YAVIN_ABORT_TIMEOUT_SEC, YAVIN_DEFAULT_TIMEOUT_MS
from ..responses import build_operation_response
from ..secrets import redact_text

logger = logging.getLogger(__name__)


class YavinHttpTransport:
    """Handle low-level HTTP requests and exception mapping."""

    def __init__(self, ip_address):
        self.ip_address = ip_address

    def post_json(self, url, payload, timeout):
        """Send POST request and return decoded JSON response."""
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()

    def _get_timeout_error_details(self, operation):
        timeout_sec = (
            YAVIN_DEFAULT_TIMEOUT_MS / 1000
            if operation == "communicating"
            else YAVIN_ABORT_TIMEOUT_SEC
        )
        error_msg = _(
            "Payment request timed out. The terminal at %(ip_addr)s did not respond "
            "within %(timeout)s seconds. The terminal may be busy or unreachable.",
            ip_addr=self.ip_address,
            timeout=int(timeout_sec),
        )
        return "timeout", error_msg, True, None

    def _get_connection_error_details(self, exception):
        error_detail = str(exception)
        if "Failed to resolve" in error_detail or "Name resolution" in error_detail:
            error_type = _("DNS resolution failed")
            error_msg = _(
                "Cannot resolve terminal address %(ip_addr)s. "
                "Please check the network configuration.",
                ip_addr=self.ip_address,
            )
        elif "Connection refused" in error_detail:
            error_type = _("Connection refused")
            error_msg = _(
                "Terminal at %(ip_addr)s refused the connection. "
                "The terminal may be offline or the service is not running.",
                ip_addr=self.ip_address,
            )
        elif "Network is unreachable" in error_detail:
            error_type = _("Network unreachable")
            error_msg = _(
                "Network unreachable. Please check your network connection to %(ip_addr)s.",
                ip_addr=self.ip_address,
            )
        else:
            error_type = _("Connection error")
            error_msg = _(
                "Cannot connect to payment terminal at %(ip_addr)s. "
                "Please check the network connection and terminal status.",
                ip_addr=self.ip_address,
            )
        return "network_error", error_msg, True, error_type

    def _get_http_error_details(self, exception):
        status_code = ""
        if hasattr(exception, "response") and exception.response is not None:
            status_code = f" (HTTP {exception.response.status_code})"
        error_msg = _(
            "HTTP error from Yavin payment terminal on %(ip_addr)s%(status_code)s: %(error)s",
            ip_addr=self.ip_address,
            status_code=status_code,
            error=str(exception),
        )
        return "issue", error_msg, False, None

    def handle_http_exception(self, exception, operation="communicating"):
        """Map transport exceptions to standardized operation responses."""
        if isinstance(exception, requests.exceptions.Timeout):
            logger.warning("Timeout %s with Yavin terminal %s", operation, self.ip_address)
            status, error_msg, retryable, error_type = self._get_timeout_error_details(operation)
        elif isinstance(exception, requests.exceptions.ConnectionError):
            logger.warning("Connection error to Yavin terminal %s: %s", self.ip_address, exception)
            status, error_msg, retryable, error_type = self._get_connection_error_details(exception)
        elif isinstance(exception, requests.exceptions.HTTPError):
            logger.warning("HTTP error from Yavin terminal %s: %s", self.ip_address, exception)
            raw_body = None
            try:
                if hasattr(exception, "response") and exception.response is not None:
                    raw_body = exception.response.text
                    if raw_body:
                        safe_body = redact_text(raw_body)
                        logger.warning(
                            "Yavin API raw response body (HTTP %s): %s",
                            exception.response.status_code,
                            safe_body[:2000] if len(safe_body) > 2000 else safe_body,
                        )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to get raw response body: %s", exc)
            status, error_msg, retryable, error_type = self._get_http_error_details(exception)
        elif isinstance(exception, requests.exceptions.RequestException):
            logger.warning(
                "Request error %s to Yavin terminal %s: %s",
                operation,
                self.ip_address,
                exception,
            )
            error_msg = _(
                "Error %(operation)s with Yavin payment terminal "
                "on %(ip_addr)s: %(error)s",
                operation=operation,
                ip_addr=self.ip_address,
                error=str(exception),
            )
            status, retryable, error_type = "issue", False, None
        else:
            logger.error(
                "Unexpected error %s with Yavin terminal %s: %s",
                operation,
                self.ip_address,
                exception,
            )
            error_msg = _(
                "Unexpected error %(operation)s with Yavin payment terminal "
                "on %(ip_addr)s: %(error)s",
                operation=operation,
                ip_addr=self.ip_address,
                error=str(exception),
            )
            status, retryable, error_type = "issue", False, None

        return build_operation_response(
            status,
            error_message=error_msg,
            retryable=True if retryable else None,
            error_type=error_type,
        )
