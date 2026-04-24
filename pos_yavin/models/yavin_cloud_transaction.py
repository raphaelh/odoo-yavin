# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Pending Yavin Cloud transactions (webhook correlation)."""

import logging

from odoo import api, fields, models

from .yavin.constants import YAVIN_TIMEOUT_ERROR_MSG

_logger = logging.getLogger(__name__)


class YavinCloudTransaction(models.Model):
    """Track a Cloud payment until the Yavin webhook delivers the final result."""

    _name = "yavin.cloud.transaction"
    _description = "Yavin Cloud payment transaction"
    _order = "id desc"

    payment_method_id = fields.Many2one(
        "pos.payment.method",
        string="Payment Method",
        required=True,
        ondelete="cascade",
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        ondelete="restrict",
    )
    idempotent_uuid = fields.Char(required=True, index=True)
    cart_id = fields.Char(index=True, help="POS order UID (cartId sent to Yavin).")
    cloud_transaction_id = fields.Char(
        string="Cloud Transaction Id",
        index=True,
        help="transaction_id returned by Yavin when the payment is pushed to the terminal.",
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    result_payload = fields.Json(string="Webhook Payload")
    error_message = fields.Text()

    _YAVIN_ALLOWED_TRANSITIONS = {
        "pending": frozenset({"done", "error"}),
        "error": frozenset({"done"}),
        "done": frozenset(),
    }

    def _yavin_transition(self, target_state, **extra_values):
        """Apply a guarded state transition on one transaction row."""
        self.ensure_one()
        allowed_targets = self._YAVIN_ALLOWED_TRANSITIONS.get(self.state, frozenset())
        if target_state not in allowed_targets:
            _logger.warning(
                "Yavin Cloud transaction invalid transition: id=%s %s -> %s",
                self.id,
                self.state,
                target_state,
            )
            return False
        values = {"state": target_state, **extra_values}
        self.write(values)
        return True

    def _yavin_mark_done(self, payload):
        """Transition transaction to done and persist webhook payload."""
        self.ensure_one()
        return self._yavin_transition(
            "done",
            result_payload=payload,
            error_message=False,
        )

    def _yavin_mark_error(self, message):
        """Transition transaction to error with user-facing message."""
        self.ensure_one()
        return self._yavin_transition("error", error_message=message)

    def _yavin_gc_domain(self):
        limit_pending = fields.Datetime.subtract(fields.Datetime.now(), hours=24)
        limit_final = fields.Datetime.subtract(fields.Datetime.now(), days=7)
        return [
            "|",
            "&",
            ("state", "=", "pending"),
            ("create_date", "<", fields.Datetime.to_string(limit_pending)),
            "&",
            ("state", "in", ("done", "error")),
            ("create_date", "<", fields.Datetime.to_string(limit_final)),
        ]

    @api.model
    def _yavin_gc_old_transactions(self):
        """Cron: remove stale pending rows and old completed rows."""
        domain = self._yavin_gc_domain()
        stale = self.search(domain, limit=5000)
        if stale:
            _logger.info("Yavin Cloud GC: unlinking %s stale transaction(s)", len(stale))
            stale.unlink()
        return True

    @api.model
    def _yavin_process_webhook(self, token, payload):
        """
        Match a Yavin webhook to a pending row and store the final payload.

        :param str token: Webhook URL token (``pos.payment.method.yavin_webhook_token``).
        :param dict payload: Parsed JSON body from Yavin.
        :return: ``True`` if processed (including no-op), ``False`` if token unknown.
        """
        method = (
            self.env["pos.payment.method"]
            .sudo()
            .search([("yavin_webhook_token", "=", token)], limit=1)
        )
        if not method:
            _logger.warning("Yavin webhook: unknown token prefix=%s", (token or "")[:8])
            return False

        if method.use_payment_terminal != "yavin" or method.yavin_effective_connection_mode != "cloud":
            _logger.warning(
                "Yavin webhook: token matched method %s but Cloud Yavin is disabled",
                method.id,
            )
            return True

        if not isinstance(payload, dict):
            return True

        trs_id = payload.get("trs_id") or payload.get("transaction_id") or ""
        cart_id = str(payload.get("cartId") or payload.get("cart_id") or "")

        open_states = [
            "|",
            ("state", "=", "pending"),
            "&",
            ("state", "=", "error"),
            ("error_message", "=", YAVIN_TIMEOUT_ERROR_MSG),
        ]

        tx = self.sudo().search(
            [
                ("payment_method_id", "=", method.id),
                ("cloud_transaction_id", "=", trs_id),
                *open_states,
            ],
            limit=1,
        )
        if not tx and trs_id:
            tx = self.sudo().search(
                [
                    ("payment_method_id", "=", method.id),
                    ("cloud_transaction_id", "=", False),
                    ("cart_id", "=", cart_id),
                    *open_states,
                ],
                order="id desc",
                limit=1,
            )

        if not tx:
            # Idempotent duplicate delivery: row already finalized (same trs_id)
            if trs_id:
                done_dup = self.sudo().search(
                    [
                        ("payment_method_id", "=", method.id),
                        ("cloud_transaction_id", "=", trs_id),
                        ("state", "=", "done"),
                    ],
                    limit=1,
                )
                if done_dup:
                    return True
            _logger.warning(
                "Yavin webhook: no pending transaction for method %s trs_id=%s cart_id=%s",
                method.id,
                trs_id,
                cart_id,
            )
            return True

        if tx.state == "done":
            return True

        if tx.state == "error" and (tx.error_message or "") != YAVIN_TIMEOUT_ERROR_MSG:
            _logger.warning(
                "Yavin webhook: transaction id=%s is in terminal error state, ignoring webhook",
                tx.id,
            )
            return True

        late_recovery = tx.state == "error" and (tx.error_message or "") == YAVIN_TIMEOUT_ERROR_MSG

        if not tx._yavin_mark_done(payload):
            return True
        if late_recovery:
            _logger.warning(
                "Yavin Cloud late webhook recovered after POS timeout: tx_id=%s trs_id=%s",
                tx.id,
                trs_id,
            )
        else:
            _logger.info(
                "Yavin webhook: matched cloud transaction id=%s payment_method_id=%s trs_id=%s cart_id=%s",
                tx.id,
                method.id,
                trs_id,
                cart_id,
            )
        return True
