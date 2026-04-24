# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Payload builder for Yavin API requests."""

import logging

logger = logging.getLogger(__name__)


class YavinPayloadBuilder:
    """Builder for Yavin API request payloads."""

    def __init__(self, pos_version_provider):
        """
        Initialize the payload builder.

        :param pos_version_provider: Provider for Odoo POS version
        """
        self.pos_version_provider = pos_version_provider

    def _build_vendor_payload(self):
        """Build vendor metadata shared by Yavin requests."""
        return {
            "softwareVersion": self.pos_version_provider.get_pos_version(),
            "softwareName": "Odoo POS",
        }

    def build_payment_payload(self, data, amount_cent, _unused_currency):
        """
        Build the payment request payload.

        :param data: Dictionary containing payment data from frontend
        :param amount_cent: Amount in cents
        :param _unused_currency: Currency record (unused)
        :return: Dictionary payload for the API request
        """
        order_uid = data.get("order_uid") or ""
        payment_id = data.get("payment_id") or ""
        cashier_name = data.get("cashier_name") or ""
        customer_data = data.get("customer")
        attempt_number = data.get("attempt_number", 1)

        # Build idempotentUuid: order_uid + '-' + payment_id + '-' + attempt_number
        idempotent_uuid = f"{order_uid}-{payment_id}-{attempt_number}"

        payload = {
            "amount": amount_cent,
            "vendor": self._build_vendor_payload(),
            "cartId": str(order_uid),  # Always include cartId, convert to string
            "transactionType": "debit",
            "idempotentUuid": idempotent_uuid,  # Always include idempotentUuid
        }

        # Add reference field with cashier name (always include if provided)
        if cashier_name:
            payload["reference"] = str(cashier_name)
        else:
            logger.warning(
                "No cashier name provided - reference field will not be included in payload"
            )

        # Add customer information if available
        if customer_data:
            customer = {}
            if customer_data.get("firstName"):
                customer["firstName"] = customer_data["firstName"]
            if customer_data.get("lastName"):
                customer["lastName"] = customer_data["lastName"]
            if customer_data.get("email"):
                customer["email"] = customer_data["email"]
            if customer_data.get("phone"):
                customer["phone"] = customer_data["phone"]
            # Only add customer object if it has at least one field
            if customer:
                payload["customer"] = customer

        return payload

    def build_abort_payload(self, order_uid, payment_id, attempt_number=1):
        """
        Build the abort payment request payload.

        :param order_uid: Order UID from frontend
        :param payment_id: Payment ID from frontend
        :param attempt_number: Attempt number for idempotentUuid (default: 1)
        :return: Dictionary payload for the abort API request
        """
        # Build idempotentUuid: order_uid + '-' + payment_id + '-' + attempt_number
        idempotent_uuid = f"{order_uid}-{payment_id}-{attempt_number}"
        return {"idempotentUuid": idempotent_uuid}

    def build_reversal_payload(  # pylint: disable=too-many-arguments
        self, amount_cent, initial_tx_id, order_uid, payment_id, attempt=1
    ):
        """
        Build the reversal request payload.

        :param amount_cent: Amount in cents to reverse
        :param initial_tx_id: ID of the initial transaction to reverse
        :param order_uid: Order UID from frontend
        :param payment_id: Payment ID from frontend
        :param attempt: Attempt number for idempotentUuid (default: 1)
        :return: Dictionary payload for the reversal API request
        """
        # Build idempotentUuid: order_uid + '-' + payment_id + '-' + attempt
        idempotent_uuid = f"{order_uid}-{payment_id}-{attempt}"

        return {
            "amount": amount_cent,
            "initialTransactionId": initial_tx_id,
            "idempotentUuid": idempotent_uuid,
            "vendor": self._build_vendor_payload(),
        }
