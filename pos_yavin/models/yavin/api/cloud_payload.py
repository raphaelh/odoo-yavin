# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Build camelCase JSON bodies for Yavin Cloud API v4 (https://api.yavin.com/docs)."""


class YavinCloudPayloadBuilder:
    """Map internal POS data to Cloud API v4 request bodies."""

    def __init__(self, pos_version_provider):
        self.pos_version_provider = pos_version_provider

    def _vendor(self):
        return {
            "softwareName": "Odoo POS",
            "softwareVersion": self.pos_version_provider.get_pos_version(),
        }

    def build_payment_payload(
        self,
        data,
        amount_cent,
        currency,
        display_tip_screen,
    ):
        """Build Cloud v4 payment body (camelCase keys)."""
        order_uid = data.get("order_uid") or ""
        payment_id = data.get("payment_id") or ""
        cashier_name = data.get("cashier_name") or ""
        customer_data = data.get("customer") or {}
        attempt_number = data.get("attempt_number", 1)
        idempotent_uuid = f"{order_uid}-{payment_id}-{attempt_number}"

        payload = {
            "amount": int(amount_cent),
            "transactionType": "debit",
            "vendor": self._vendor(),
            "currencyCode": currency.name,
            "idempotentUuid": idempotent_uuid,
            "enableGiftScreen": bool(display_tip_screen),
            "giftAmount": 0,
        }
        if order_uid:
            payload["cartId"] = str(order_uid)
        if cashier_name:
            payload["reference"] = str(cashier_name)

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
            if customer:
                payload["customer"] = customer

        return payload, idempotent_uuid

    def build_reversal_payload(self, amount_cent, initial_tx_id, order_uid, payment_id, attempt=1):
        """Build Cloud v4 reversal body (camelCase keys)."""
        idempotent_uuid = f"{order_uid}-{payment_id}-{attempt}"
        return {
            "amount": int(amount_cent),
            "initialTransactionId": initial_tx_id,
            "idempotentUuid": idempotent_uuid,
            "vendor": self._vendor(),
        }
