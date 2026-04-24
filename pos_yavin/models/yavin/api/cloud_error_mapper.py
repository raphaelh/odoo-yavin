# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Map Yavin Cloud HTTP and transport errors to POS responses."""

import logging

import requests
from odoo import _

from ..responses import build_operation_response
from ..secrets import redact_text

logger = logging.getLogger(__name__)


class YavinCloudErrorMapper:
    """Convert Cloud request exceptions into normalized operation responses."""

    def map_http_error(self, exc, serial, secrets=()):
        """Map requests errors to operation responses (terminal label uses serial)."""
        safe_error = redact_text(str(exc), secrets=secrets)
        if isinstance(exc, requests.exceptions.Timeout):
            return build_operation_response(
                "timeout",
                error_message=_(
                    "Yavin Cloud API did not respond in time for terminal %(serial)s.",
                    serial=serial,
                ),
                retryable=True,
            )
        if isinstance(exc, requests.exceptions.ConnectionError):
            return build_operation_response(
                "network_error",
                error_message=_(
                    "Cannot reach Yavin Cloud API for terminal %(serial)s.",
                    serial=serial,
                ),
                retryable=True,
            )
        if isinstance(exc, requests.exceptions.HTTPError):  # subclass of RequestException
            body = ""
            detail = ""
            try:
                if exc.response is not None:
                    body = exc.response.text or ""
                    if body:
                        try:
                            err_json = exc.response.json()
                            detail = err_json.get("message") or err_json.get("error") or ""
                        except ValueError:
                            detail = ""
            except Exception:  # pylint: disable=broad-exception-caught
                body = ""
            detail = redact_text(detail, secrets=secrets)
            safe_body = redact_text(body, secrets=secrets)
            logger.warning(
                "Yavin Cloud HTTP error for serial %s: %s; body=%s",
                serial,
                safe_error,
                safe_body[:2000] if safe_body else "",
            )
            msg = _(
                "Yavin Cloud API HTTP error for terminal %(serial)s: %(error)s",
                serial=serial,
                error=safe_error,
            )
            if detail:
                msg = f"{msg} ({detail})"
            return build_operation_response("issue", error_message=msg)

        logger.exception("Yavin Cloud unexpected error for serial %s", serial)
        return build_operation_response(
            "issue",
            error_message=_(
                "Unexpected error calling Yavin Cloud API for terminal %(serial)s: %(error)s",
                serial=serial,
                error=safe_error,
            ),
        )
