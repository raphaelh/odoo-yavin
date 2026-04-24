"""Resolve original Yavin transactions for POS refunds."""

import logging


logger = logging.getLogger(__name__)


class YavinRefundTransactionResolver:
    """Fetch original successful Yavin payment transactions for refunded lines."""

    def __init__(self, env):
        self.env = env

    def resolve_original_transactions(self, data):
        """
        Resolve Yavin transactions from original order lines referenced by refund data.

        :param dict data: RPC payload containing refunded orderline identifiers.
        :return: List of transaction dictionaries with `transaction_id` and `amount`.
        :rtype: list[dict]
        """
        refunded_orderline_ids = data.get("refunded_orderline_ids")

        original_orders = self.env["pos.order"]

        if refunded_orderline_ids:
            # Preferred method: direct lookup from original line IDs.
            original_lines = self.env["pos.order.line"].browse(refunded_orderline_ids)
            original_orders = original_lines.mapped("order_id")
        else:
            return []

        if not original_orders:
            logger.warning("No original order found for refund")
            return []

        transactions = []
        for original_order in original_orders:
            yavin_payments = original_order.payment_ids.filtered(
                lambda p: p.payment_method_id.use_payment_terminal == "yavin"
                and p.transaction_id
                and p.payment_status == "done"
            )

            if not yavin_payments:
                logger.debug(
                    "No valid Yavin payments found for order %s",
                    original_order.name,
                )

            for payment in yavin_payments:
                transactions.append(
                    {
                        "transaction_id": payment.transaction_id,
                        "amount": payment.amount,
                    }
                )

        return transactions
