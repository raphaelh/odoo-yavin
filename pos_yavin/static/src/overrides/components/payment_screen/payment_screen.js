/** @odoo-module */
/*
    Copyright 2026 Raphaël HUCK
    @author: Raphaël HUCK
    License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
*/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { onMounted, useEffect } from "@odoo/owl";
import { setYavinPaymentStatus } from "@pos_yavin/payment/lifecycle_utils";
import { getPosRefundLinesTotalWithTax } from "@pos_yavin/overrides/models/models";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);

        // Track processed orders to avoid duplicate processing
        this._yavinProcessedOrders = new Set();
        this._yavinRefundTransactionsByOrder = new Map();

        // Let the payment terminal recover or reset restored lines using the shared lifecycle rules.
        onMounted(() => {
            this._recoverCurrentYavinTransactions();
        });

        // Watch for order changes and screen visibility to auto-generate payment lines
        useEffect(
            () => {
                this._recoverCurrentYavinTransactions();
                void this._checkAndGenerateRefundPaymentLines();
                this._syncYavinRefundPaymentCap();
            },
            () => {
                const order = this.currentOrder;
                const isShown = this.props.isShown;
                const refundSig =
                    order?.get_orderlines?.() &&
                    order
                        .get_orderlines()
                        .filter((l) => l.refunded_orderline_id)
                        .map((l) => `${l.refunded_orderline_id}:${l.get_quantity()}`)
                        .join("|");
                return [order?.uid || null, isShown, refundSig || ""];
            }
        );
    },

    _recoverCurrentYavinTransactions() {
        const order = this.currentOrder;
        if (!order || !this.props.isShown) {
            return;
        }
        for (const paymentMethod of this.pos.payment_methods) {
            if (paymentMethod.use_payment_terminal !== "yavin") {
                continue;
            }
            if (paymentMethod.payment_terminal?.check_pending_transactions) {
                paymentMethod.payment_terminal.check_pending_transactions(order);
            }
        }
    },

    _getYavinOrderKey(order) {
        return order?.uid || order?.cid || null;
    },

    _isYavinRefundOrder(order) {
        return Boolean(order?.get_orderlines().some((line) => line.refunded_orderline_id));
    },

    _setYavinOriginalTransactions(order, transactions) {
        const orderKey = this._getYavinOrderKey(order);
        if (!orderKey) {
            return;
        }
        if (transactions?.length) {
            this._yavinRefundTransactionsByOrder.set(orderKey, [...transactions]);
        } else {
            this._yavinRefundTransactionsByOrder.delete(orderKey);
        }
    },

    _getYavinOriginalTransactions(order) {
        const orderKey = this._getYavinOrderKey(order);
        return orderKey ? (this._yavinRefundTransactionsByOrder.get(orderKey) || []) : [];
    },

    /**
     * Keep Yavin refund payment lines aligned with the sum of selected refund order lines
     * (refunded_orderline_id), capped per original transaction amount.
     */
    _syncYavinRefundPaymentCap() {
        const order = this.currentOrder;
        if (!order || !this.props.isShown || !this._isYavinRefundOrder(order)) {
            return;
        }
        const txs = this._getYavinOriginalTransactions(order);
        if (!txs?.length) {
            return;
        }
        const selectionSigned = getPosRefundLinesTotalWithTax(order);
        const selectionAbs = Math.abs(selectionSigned);
        const yavinRefundLines = order.paymentlines.filter(
            (pl) =>
                pl.payment_method?.use_payment_terminal === "yavin" &&
                pl.yavin_original_transaction_id
        );
        let remainingAbs = selectionAbs;
        for (const pl of yavinRefundLines) {
            const tx = txs.find((t) => t.transaction_id === pl.yavin_original_transaction_id);
            if (!tx) {
                continue;
            }
            const txAbs = Math.abs(tx.amount);
            const lineAbs = Math.min(remainingAbs, txAbs);
            pl.set_amount(-lineAbs);
            remainingAbs = Math.max(0, remainingAbs - lineAbs);
        }
    },

    async _checkAndGenerateRefundPaymentLines() {
        const order = this.currentOrder;
        if (!order || !this.props.isShown) {
            return;
        }

        // Skip if we already processed this order
        const orderKey = this._getYavinOrderKey(order);
        if (this._yavinProcessedOrders.has(orderKey)) {
            return;
        }

        if (!this._isYavinRefundOrder(order)) {
            return;
        }

        // Auto-generate payment lines for refund orders with Yavin transactions
        const hasYavinRefundLines = order.paymentlines.some(
            (line) => line.payment_method?.use_payment_terminal === "yavin"
                && line.yavin_original_transaction_id
        );

        if (!hasYavinRefundLines) {
            try {
                const refundedOrderlineIds = order.get_orderlines()
                    .map((line) => line.refunded_orderline_id)
                    .filter((id) => id);

                const originalTransactions = await this.orm.silent.call(
                    "pos.payment.method",
                    "yavin_get_original_transactions",
                    [{
                        order_uid: order.uid || "",
                        session_id: this.pos.pos_session.id,
                        refunded_orderline_ids: refundedOrderlineIds,
                    }]
                );

                this._setYavinOriginalTransactions(order, originalTransactions);

                if (originalTransactions?.length) {
                    const yavinPaymentMethod = this.pos.payment_methods.find(
                        (pm) => pm.use_payment_terminal === "yavin"
                    );

                    if (yavinPaymentMethod) {
                        for (const tx of originalTransactions) {
                            const existingLine = order.paymentlines.find(
                                (pl) => pl.yavin_original_transaction_id === tx.transaction_id
                            );
                            if (existingLine) {
                                continue;
                            }

                            const currentPaymentTotal = order.paymentlines.reduce(
                                (sum, line) => sum + line.get_amount(),
                                0
                            );
                            const selectionTotalSigned = getPosRefundLinesTotalWithTax(order);
                            if (Math.abs(currentPaymentTotal - selectionTotalSigned) < 0.01) {
                                break;
                            }

                            const paymentLine = order.add_paymentline(yavinPaymentMethod);
                            if (!paymentLine) {
                                break;
                            }

                            // Cap reversal amount to selected refund lines (partial refunds).
                            // Original transaction amount is the full card capture, not the refunded subtotal.
                            const remainingSigned = selectionTotalSigned - currentPaymentTotal;
                            const remainingAbs = Math.abs(remainingSigned);
                            const txAmountAbs = Math.abs(tx.amount);
                            const lineAmountAbs = Math.min(remainingAbs, txAmountAbs);
                            paymentLine.set_amount(-lineAmountAbs);
                            paymentLine.yavin_original_transaction_id = tx.transaction_id;
                        }
                    }
                }
                this._yavinProcessedOrders.add(orderKey);
            } catch {
                // Keep screen interactive even if refund-line prefill cannot run.
            }
        } else {
            this._yavinProcessedOrders.add(orderKey);
        }
    },

    async addNewPaymentLine(paymentMethod) {
        // Call original method first to create the line
        const result = await super.addNewPaymentLine(...arguments);

        if (paymentMethod.use_payment_terminal === "yavin") {
            const order = this.currentOrder;
            const originalTransactions = this._getYavinOriginalTransactions(order);
            if (originalTransactions.length > 0) {
                // Find the newly created line (it's the selected one)
                const paymentLine = order.selected_paymentline;

                if (paymentLine) {
                    // Find the first unused transaction
                    const usedTransactionIds = new Set(
                        order.paymentlines
                            .map(pl => pl.yavin_original_transaction_id)
                            .filter(id => id)
                    );

                    const nextTransaction = originalTransactions.find(
                        tx => !usedTransactionIds.has(tx.transaction_id)
                    );

                    if (nextTransaction) {
                        const selectionTotalSigned = getPosRefundLinesTotalWithTax(order);
                        const otherPaymentsTotal = order.paymentlines
                            .filter((pl) => pl.cid !== paymentLine.cid)
                            .reduce((sum, line) => sum + line.get_amount(), 0);
                        const remainingSigned = selectionTotalSigned - otherPaymentsTotal;
                        const remainingAbs = Math.abs(remainingSigned);
                        const txAmountAbs = Math.abs(nextTransaction.amount);
                        const lineAmountAbs = Math.min(remainingAbs, txAmountAbs);
                        paymentLine.set_amount(-lineAmountAbs);
                        paymentLine.yavin_original_transaction_id = nextTransaction.transaction_id;
                    }
                }
            }
        }
        return result;
    },

    async sendPaymentReverse(line) {
        const paymentTerminal = line.payment_method.payment_terminal;
        setYavinPaymentStatus(line, "reversing");

        const isReversalSuccessful = await paymentTerminal.send_payment_reversal(line.cid);
        if (line.payment_method?.use_payment_terminal !== "yavin") {
            if (isReversalSuccessful) {
                line.set_amount(0);
                setYavinPaymentStatus(line, "reversed");
            } else {
                line.can_be_reversed = false;
                setYavinPaymentStatus(line, "done");
            }
            return;
        }

        if (isReversalSuccessful) {
            if (line.amount >= 0) {
                line.set_amount(0);
                setYavinPaymentStatus(line, "reversed");
            } else {
                setYavinPaymentStatus(line, "done");
            }
            line.can_be_reversed = false;
            return;
        }

        line.can_be_reversed = true;
        setYavinPaymentStatus(line, "done");
    }
});
