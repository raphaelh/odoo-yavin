# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Response parser for Yavin API responses."""

import json
import logging

from odoo import _

from ..responses import build_operation_response

logger = logging.getLogger(__name__)


class YavinResponseParser:
    """Parser for Yavin API responses."""

    def __init__(self, amount_converter, env):
        """
        Initialize the response parser.

        :param amount_converter: Converter for amount conversions
        :param env: Odoo environment
        """
        self.amount_converter = amount_converter
        self.env = env

    def parse_payment_response(self, response_data, currency):
        """
        Parse the payment response from Yavin API.

        :param response_data: JSON response data from API
        :param currency: Currency record
        :return: Dictionary with operation_status and payment data
        """
        status = response_data.get("status", "")
        if status == "ok":
            # Success
            transaction_id = response_data.get("transactionId", "")
            scheme = response_data.get("scheme", "")
            issuer = response_data.get("issuer", "")
            client_card_ticket = response_data.get("clientCardTicket", "")
            gift_amount_cent = response_data.get("giftAmount", 0)  # In cents

            # Convert from cents to monetary unit
            gift_amount = self.amount_converter.convert_cents_to_amount(
                gift_amount_cent, currency
            )

            res = build_operation_response(
                "success",
                transaction_id=transaction_id,
                card_type=scheme,
                yavin_issuer=issuer,
                ticket=client_card_ticket,
            )
            # Add tip if present
            if gift_amount > 0:
                res["gift_amount"] = gift_amount
                logger.info(
                    "Payment successful with tip: tx_id=%s, scheme=%s, tip=%s %s",
                    transaction_id,
                    scheme,
                    gift_amount,
                    currency.name,
                )
            else:
                logger.info(
                    "Payment successful: transaction_id=%s, scheme=%s",
                    transaction_id,
                    scheme,
                )
            return res

        # Failure - status == "ko" or other
        # Get error message from response, or use generic message if missing/empty
        error_msg = response_data.get("message") or _(
            "The payment transaction has failed."
        )
        res = build_operation_response("failure", error_message=error_msg)
        # Log full response for debugging when message is empty
        if not response_data.get("message"):
            logger.warning(
                "Payment failed with empty message - full response: %s",
                json.dumps(response_data, indent=2)
            )
        logger.info(
            "Payment failed: status=%s, message=%s, transactionId=%s",
            status,
            response_data.get("message", ""),
            response_data.get("transactionId", ""),
        )
        return res

    def parse_reversal_response(self, response_data):
        """
        Parse the reversal response from Yavin API.

        :param response_data: JSON response data from API
        :return: Dictionary with operation_status and reversal data
        """
        status = response_data.get("status", "")
        if status == "ok":
            # Success
            logger.info("Reversal successful")
            return build_operation_response("success")

        # Failure
        error_msg = response_data.get("message") or _(
            "The reversal transaction has failed."
        )
        if not response_data.get("message"):
            logger.warning(
                "Reversal failed with empty message - full response: %s",
                json.dumps(response_data, indent=2)
            )
        logger.info(
            "Reversal failed: status=%s, message=%s",
            status,
            response_data.get("message", ""),
        )
        return build_operation_response("failure", error_message=error_msg)

    def parse_cloud_webhook_payload(self, payload, currency):
        """
        Map a Yavin Cloud webhook JSON body to the same contract as ``parse_payment_response``.

        Cloud payloads use mostly snake_case (see Yavin Cloud API documentation).
        """
        if not payload or not isinstance(payload, dict):
            return build_operation_response(
                "issue",
                error_message=_("Invalid webhook payload."),
            )

        status = (payload.get("status") or "").lower()
        trs_id = payload.get("trs_id") or payload.get("transaction_id") or ""
        gift_amount_cent = payload.get("gift_amount")
        if gift_amount_cent is None:
            gift_amount_cent = payload.get("giftAmount") or 0

        client_ticket = payload.get("client_ticket") or payload.get("clientCardTicket") or ""
        scheme = payload.get("scheme") or payload.get("medium") or ""
        issuer = payload.get("issuer") or ""

        if status == "ok":
            gift_amount = self.amount_converter.convert_cents_to_amount(
                int(gift_amount_cent or 0), currency
            )
            res = build_operation_response(
                "success",
                transaction_id=trs_id,
                card_type=scheme,
                yavin_issuer=issuer,
                ticket=client_ticket,
            )
            if gift_amount > 0:
                res["gift_amount"] = gift_amount
            return res

        error_msg = payload.get("message") or _(
            "The payment transaction has failed."
        )
        return build_operation_response("failure", error_message=error_msg)
