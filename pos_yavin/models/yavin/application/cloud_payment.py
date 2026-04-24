# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Yavin Cloud payment flow (start + client-side polling for webhook)."""

import json
import logging

import requests
from odoo import _

from ..api.cloud_client import YavinCloudClient
from ..api.cloud_error_mapper import YavinCloudErrorMapper
from ..api.cloud_payload import YavinCloudPayloadBuilder
from ..api.response_parser import YavinResponseParser
from ..constants import YAVIN_DEFAULT_TIMEOUT_MS, YAVIN_TIMEOUT_ERROR_MSG
from ..formatting.amount_converter import YavinAmountConverter
from ..responses import build_operation_response
from ..secrets import redact_payload
from ..version.provider import YavinVersionProvider

logger = logging.getLogger(__name__)


def _normalize_cloud_json_keys(data):
    """Read common keys from mixed-case Cloud JSON responses."""
    if not data or not isinstance(data, dict):
        return None, None, None
    tid = data.get("transaction_id") or data.get("transactionId")
    status = (data.get("status") or "").lower()
    message = data.get("message") or ""
    return tid, status, message


class YavinCloudPaymentService:
    """Run Cloud payment, abort, and reversal flows."""

    def __init__(self, env):
        self.env = env
        self._cloud_error_mapper = YavinCloudErrorMapper()

    def _parser(self):
        return YavinResponseParser(YavinAmountConverter(), self.env)

    def _handle_cloud_http_error(self, exc, serial, secrets=()):
        """Delegate Cloud transport error mapping to a dedicated helper."""
        return self._cloud_error_mapper.map_http_error(exc, serial, secrets=secrets)

    def _timeout_user_message(self):
        return _(
            "No webhook from Yavin within the configured time. "
            "Check that the webhook URL is registered in Yavin and reachable over HTTPS."
        )

    def _commit_cloud_change(self, tx, values, reason):
        """Write Cloud transaction values then force an intentional commit."""
        tx.write(values)
        self.env.cr.commit()  # pylint: disable=invalid-commit
        logger.info("Yavin Cloud transaction committed: tx_id=%s reason=%s", tx.id, reason)

    def _commit_cloud_state(self, tx, state, reason, **extra_values):
        """Update Cloud transaction state with a single intentional commit."""
        if tx._yavin_transition(state, **extra_values):
            self.env.cr.commit()  # pylint: disable=invalid-commit
            logger.info(
                "Yavin Cloud transaction committed: tx_id=%s reason=%s",
                tx.id,
                reason,
            )
            return True
        logger.warning(
            "Yavin Cloud transaction skipped commit after refused transition: tx_id=%s target=%s reason=%s",
            tx.id,
            state,
            reason,
        )
        return False

    def read_status(self, payment_method, tx_id):
        """Read cloud transaction state (short RPC)."""
        CloudTx = self.env["yavin.cloud.transaction"].sudo()
        row = CloudTx.browse(tx_id)
        if not row.exists():
            return build_operation_response(
                "issue",
                error_message=_("Yavin Cloud transaction record was removed."),
            )
        if row.payment_method_id.id != payment_method.id:
            return build_operation_response(
                "issue",
                error_message=_("Unknown transaction."),
            )
        if row.state == "pending":
            return build_operation_response(
                "pending",
                retryable=True,
                yavin_tx_id=row.id,
            )
        if row.state == "done" and row.result_payload:
            cur = row.currency_id
            return self._parser().parse_cloud_webhook_payload(row.result_payload, cur)
        if row.state == "error":
            if (row.error_message or "") == YAVIN_TIMEOUT_ERROR_MSG:
                return build_operation_response(
                    "timeout",
                    error_message=self._timeout_user_message(),
                    retryable=True,
                    yavin_tx_id=row.id,
                )
            return build_operation_response(
                "failure",
                error_message=row.error_message
                or _("The payment transaction has failed."),
                yavin_tx_id=row.id,
            )
        return build_operation_response(
            "issue",
            error_message=_("Invalid Yavin Cloud transaction state."),
            yavin_tx_id=row.id,
        )

    def expire_if_pending(self, payment_method, tx_id):
        """Mark pending row as timed out if still pending, then return read_status."""
        CloudTx = self.env["yavin.cloud.transaction"].sudo()
        row = CloudTx.browse(tx_id)
        if not row.exists():
            return build_operation_response(
                "issue",
                error_message=_("Yavin Cloud transaction record was removed."),
            )
        if row.payment_method_id.id != payment_method.id:
            return build_operation_response(
                "issue",
                error_message=_("Unknown transaction."),
            )
        if row.state == "pending":
            self._commit_cloud_state(
                row,
                "error",
                "expire_pending_timeout",
                error_message=YAVIN_TIMEOUT_ERROR_MSG,
            )
            logger.warning("Yavin Cloud expire by POS: tx_id=%s", tx_id)
        return self.read_status(payment_method, tx_id)

    def start_payment(self, payment_method, data, amount, currency, validator, extractor):
        """Start Cloud payment; POS polls read_status until webhook or expire."""
        credentials, error = validator.validate_cloud_credentials(payment_method)
        if error:
            return error

        serial, api_key = credentials
        customer_data = extractor.extract_customer_data(data.get("partner_id"))
        cashier_name = data.get("cashier_name") or extractor.extract_cashier_name(
            data.get("session_id")
        )
        enriched = dict(data)
        enriched["customer"] = customer_data
        enriched["cashier_name"] = cashier_name

        amount_cent = YavinAmountConverter().convert_amount_to_cents(amount, currency)
        builder = YavinCloudPayloadBuilder(YavinVersionProvider())
        payload, idempotent_uuid = builder.build_payment_payload(
            enriched,
            amount_cent,
            currency,
            payment_method.yavin_display_tip,
        )
        cart_id = str(enriched.get("order_uid") or "")

        CloudTx = self.env["yavin.cloud.transaction"].sudo()
        existing = CloudTx.search(
            [("idempotent_uuid", "=", idempotent_uuid)],
            order="id desc",
            limit=1,
        )
        if existing:
            if existing.state == "done" and existing.result_payload:
                logger.info(
                    "Yavin Cloud start: tx_id=%s cart_id=%s reuse=done_immediate",
                    existing.id,
                    cart_id,
                )
                return self._parser().parse_cloud_webhook_payload(
                    existing.result_payload,
                    existing.currency_id,
                )
            if existing.state == "error":
                if (existing.error_message or "") == YAVIN_TIMEOUT_ERROR_MSG:
                    return build_operation_response(
                        "timeout",
                        error_message=self._timeout_user_message(),
                        retryable=True,
                        yavin_tx_id=existing.id,
                    )
                return build_operation_response(
                    "failure",
                    error_message=existing.error_message
                    or _("The payment transaction has failed."),
                    yavin_tx_id=existing.id,
                )
            logger.info(
                "Yavin Cloud start: tx_id=%s cart_id=%s reuse=pending",
                existing.id,
                cart_id,
            )
            return build_operation_response(
                "pending",
                retryable=True,
                yavin_tx_id=existing.id,
            )

        tx = CloudTx.create(
            {
                "payment_method_id": payment_method.id,
                "idempotent_uuid": idempotent_uuid,
                "cart_id": cart_id,
                "currency_id": currency.id,
            }
        )
        tx.flush_recordset()
        self.env.cr.commit()  # pylint: disable=invalid-commit
        logger.info(
            "Yavin Cloud transaction committed: tx_id=%s reason=%s",
            tx.id,
            "create_pending_before_http_call",
        )

        client = YavinCloudClient(api_key, serial)
        http_timeout = min(60.0, (data.get("timeout") or YAVIN_DEFAULT_TIMEOUT_MS) / 1000.0)
        try:
            start_response = client.start_payment(payload, http_timeout)
        except (requests.exceptions.RequestException, ValueError) as exc:
            error_response = self._handle_cloud_http_error(exc, serial, secrets=(api_key,))
            self._commit_cloud_state(
                tx,
                "error",
                "start_payment_http_error",
                error_message=error_response.get("error_message"),
            )
            return error_response

        tid, start_status, start_message = _normalize_cloud_json_keys(start_response)
        safe_start_response = redact_payload(start_response, secrets=(api_key,))
        logger.debug(
            "Yavin Cloud start response: %s",
            json.dumps(safe_start_response, indent=2),
        )

        if start_status == "ko":
            self._commit_cloud_state(
                tx,
                "error",
                "start_payment_rejected_by_cloud",
                error_message=start_message or _("Failed to reach the terminal."),
                cloud_transaction_id=tid,
            )
            return build_operation_response(
                "failure",
                error_message=start_message or _("Failed to reach the terminal."),
            )

        if not tid:
            self._commit_cloud_state(
                tx,
                "error",
                "start_payment_missing_transaction_id",
                error_message="Missing transaction_id in Yavin Cloud response",
            )
            return build_operation_response(
                "issue",
                error_message=_("Invalid response from Yavin Cloud API (missing transaction id)."),
            )

        self._commit_cloud_change(
            tx,
            {"cloud_transaction_id": tid},
            "persist_cloud_transaction_id",
        )

        logger.info(
            "Yavin Cloud start: tx_id=%s cart_id=%s reuse=False",
            tx.id,
            cart_id,
        )
        return build_operation_response(
            "pending",
            retryable=True,
            yavin_tx_id=tx.id,
        )

    def send_payment(self, payment_method, data, amount, currency, validator, extractor):
        """Backward-compatible alias: Cloud payment start only (POS polls separately)."""
        return self.start_payment(
            payment_method, data, amount, currency, validator, extractor
        )

    def abort_payment(self, payment_method, order_uid, payment_id, attempt_num, validator):
        """Call Cloud abort endpoint."""
        credentials, error = validator.validate_cloud_credentials(payment_method)
        if error:
            return error
        serial, api_key = credentials
        idempotent_uuid = f"{order_uid}-{payment_id}-{attempt_num}"
        client = YavinCloudClient(api_key, serial)
        try:
            response = client.abort(idempotent_uuid, 15.0)
        except (requests.exceptions.RequestException, ValueError) as exc:
            return self._handle_cloud_http_error(exc, serial, secrets=(api_key,))

        status = (response.get("status") or "").lower()
        if status == "ok":
            return build_operation_response("success")
        message = response.get("message") or _("Failed to abort payment")
        return build_operation_response("failure", error_message=message)

    def send_reversal(self, payment_method, data, amount, currency, validator):
        """Call Cloud reversal endpoint (synchronous)."""
        credentials, error = validator.validate_cloud_credentials(payment_method)
        if error:
            return error
        serial, api_key = credentials
        order_uid = data.get("order_uid") or ""
        payment_id = data.get("payment_id") or ""
        initial_tx_id = data.get("initial_transaction_id") or ""
        amount_cent = YavinAmountConverter().convert_amount_to_cents(amount, currency)
        builder = YavinCloudPayloadBuilder(YavinVersionProvider())
        payload = builder.build_reversal_payload(
            amount_cent,
            initial_tx_id,
            order_uid,
            payment_id,
            data.get("attempt_number", 1),
        )
        timeout_sec = (data.get("timeout") or YAVIN_DEFAULT_TIMEOUT_MS) / 1000.0
        client = YavinCloudClient(api_key, serial)
        try:
            response = client.reversal(payload, min(timeout_sec, 65.0))
        except (requests.exceptions.RequestException, ValueError) as exc:
            return self._handle_cloud_http_error(exc, serial, secrets=(api_key,))
        return self._parser().parse_reversal_response(response)
