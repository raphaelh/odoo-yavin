# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""HTTP client for Yavin Cloud API (v4)."""

import logging

import requests

from ..constants import (
    YAVIN_CLOUD_ABORT_PATH,
    YAVIN_CLOUD_API_BASE_URL,
    YAVIN_CLOUD_PAYMENT_PATH,
    YAVIN_CLOUD_REVERSAL_PATH,
)
from ..secrets import normalize_secret

logger = logging.getLogger(__name__)


class YavinCloudClient:
    """Low-level POST helper for Yavin Cloud endpoints."""

    def __init__(self, api_key, serial_number):
        self.api_key = normalize_secret(api_key)
        self.serial_number = normalize_secret(serial_number)

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "Yavin-Secret": self.api_key,
        }

    def _post(self, path, payload, timeout_sec):
        url = f"{YAVIN_CLOUD_API_BASE_URL}{path}"
        response = requests.post(
            url,
            json=payload,
            headers=self._headers(),
            timeout=timeout_sec,
        )
        response.raise_for_status()
        return response.json()

    def start_payment(self, payload, timeout_sec):
        """POST /api/v4/pos/payment/."""
        body = dict(payload)
        body.setdefault("serialNumber", self.serial_number)
        logger.info("Yavin Cloud: starting payment for serial %s", self.serial_number)
        return self._post(YAVIN_CLOUD_PAYMENT_PATH, body, timeout_sec)

    def abort(self, idempotent_uuid, timeout_sec):
        """POST /api/v4/pos/abort/."""
        payload = {
            "serialNumber": self.serial_number,
            "idempotentUuid": idempotent_uuid,
        }
        logger.info("Yavin Cloud: abort for serial %s", self.serial_number)
        return self._post(YAVIN_CLOUD_ABORT_PATH, payload, timeout_sec)

    def reversal(self, payload, timeout_sec):
        """POST /api/v4/pos/reversal/."""
        body = dict(payload)
        return self._post(YAVIN_CLOUD_REVERSAL_PATH, body, timeout_sec)
