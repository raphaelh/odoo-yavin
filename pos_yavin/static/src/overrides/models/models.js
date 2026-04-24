/** @odoo-module */
/*
    Copyright 2026 Raphaël HUCK
    @author: Raphaël HUCK
    License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
*/

import { PaymentYavin } from "@pos_yavin/payment/payment_yavin";
import {
    getYavinRecoveryWindowMs,
    getYavinStaleStatus,
    isYavinBlockingStatus,
    isYavinPaymentLine,
    setYavinPaymentStatus,
} from "@pos_yavin/payment/lifecycle_utils";
import { PosStore, register_payment_method } from "@point_of_sale/app/store/pos_store";
import { Order, Payment } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";

/**
 * Get the tip product ID, even if iface_tipproduct is disabled.
 * This function tries multiple strategies to find the tip product:
 * 1. Use pos.config.tip_product_id if configured
 * 2. Search for product with code "TIPS" in local database
 * 
 * @param {Object} pos - The POS store instance
 * @returns {number|null} The tip product ID or null if not found
 */
export function getTipProductId(pos) {
    // Strategy 1: Use configured tip_product_id if available
    if (pos.config.tip_product_id && pos.config.tip_product_id[0]) {
        const tipProduct = pos.db.get_product_by_id(pos.config.tip_product_id[0]);
        if (tipProduct) {
            return tipProduct.id;
        }
    }

    // Strategy 2: Search for product with code "TIPS" in local database
    // The POS database might have the product even if not configured
    const allProducts = pos.db.search_product('TIPS');
    if (allProducts && allProducts.length > 0) {
        // Find exact match by code
        const tipProduct = allProducts.find(p => p.default_code === 'TIPS');
        if (tipProduct) {
            return tipProduct.id;
        }
    }

    return null;
}

export function getOrderYavinPaymentMethod(order) {
    if (order?.paymentlines?.length) {
        for (const payment of order.paymentlines) {
            if (payment.payment_method?.use_payment_terminal === "yavin") {
                return payment.payment_method;
            }
        }
    }
    return null;
}

export function shouldDisplayYavinTip(order, pos) {
    const yavinPaymentMethod = getOrderYavinPaymentMethod(order);
    if (!yavinPaymentMethod) {
        return true;
    }
    return Boolean(pos?.config?.iface_tipproduct) && yavinPaymentMethod.yavin_display_tip !== false;
}

export function filterYavinTipLines(order, pos, lines) {
    if (shouldDisplayYavinTip(order, pos)) {
        return lines;
    }
    const tipProductId = getTipProductId(pos);
    if (!tipProductId) {
        return lines;
    }
    return lines.filter((line) => !(line.product && line.product.id === tipProductId));
}

/**
 * Sum of line TTC amounts that are linked to an original order line (actual refund selection).
 * Matches what the user chose on the refund ticket; excludes stray lines without refunded_orderline_id.
 *
 * @param {Object} order POS order with get_orderlines()
 * @returns {number}
 */
export function getPosRefundLinesTotalWithTax(order) {
    if (!order?.get_orderlines) {
        return 0;
    }
    let total = 0;
    for (const line of order.get_orderlines()) {
        if (line.refunded_orderline_id) {
            total += line.get_price_with_tax();
        }
    }
    return total;
}

register_payment_method("yavin", PaymentYavin);

// Patch PosStore to trigger payment status check after loading orders
patch(PosStore.prototype, {
    async load_orders() {
        await super.load_orders(...arguments);

        // Clear stale blocking statuses BEFORE check_pending_transactions.
        // This prevents "There is already an electronic payment in progress" on first
        // transaction when a restored order has orphaned waitingCard/waiting statuses.
        this._clearStaleYavinPaymentStatuses();

        // After orders are loaded, trigger checks on payment terminals for every restored order.
        for (const order of this.get_order_list()) {
            for (const pm of this.payment_methods) {
                if (pm.payment_terminal && pm.payment_terminal.check_pending_transactions) {
                    pm.payment_terminal.check_pending_transactions(order);
                }
            }
        }
    },

    /**
     * Clear blocking payment statuses from Yavin lines that are outside the recovery window.
     * These orphaned statuses (e.g. from a previous session or page refresh) would
     * otherwise block adding new payment lines with "electronic payment in progress".
     */
    _clearStaleYavinPaymentStatuses() {
        const now = Date.now();

        for (const order of this.get_order_list()) {
            for (const line of order.get_paymentlines()) {
                if (!isYavinPaymentLine(line)) {
                    continue;
                }
                const status = line.get_payment_status();
                if (!status || !isYavinBlockingStatus(status)) {
                    continue;
                }
                // Skip if a payment request is actively in progress
                if (line.yavin_request_in_progress) {
                    continue;
                }
                const requestTime = line.yavin_payment_request_time || 0;
                if (now - requestTime >= getYavinRecoveryWindowMs(line) || requestTime === 0) {
                    const staleStatus = getYavinStaleStatus(line);
                    line.yavin_abort_state = null;
                    line.yavin_request_in_progress = false;
                    setYavinPaymentStatus(line, staleStatus, { force: true });
                    if (staleStatus === "done") {
                        line.can_be_reversed = true;
                        line.yavin_operation_type = null;
                    }
                }
            }
        }
    },
});

// Override export_for_printing to include tip in receipt data
patch(Order.prototype, {
    export_for_printing() {
        const result = super.export_for_printing(...arguments);
        // Add tip to exported data for receipt
        result.tip_amount = this.tip_amount || 0;
        result.yavin_display_tip = shouldDisplayYavinTip(this, this.pos);
        result.orderlines = filterYavinTipLines(this, this.pos, result.orderlines);
        return result;
    },
});

// Patch Payment to export and load yavin_issuer
patch(Payment.prototype, {
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        if (this.payment_method?.use_payment_terminal === 'yavin') {
            this.yavin_issuer = json.yavin_issuer;
            this.yavin_attempt_number = json.yavin_attempt_number;
            this.yavin_payment_request_time = json.yavin_payment_request_time;
            this.yavin_original_transaction_id = json.yavin_original_transaction_id;
            this.yavin_last_failure_type = json.yavin_last_failure_type;
            this.yavin_last_reversal_failure_type = json.yavin_last_reversal_failure_type;
            this.yavin_abort_state = json.yavin_abort_state;
            this.yavin_operation_type = json.yavin_operation_type;
            this.yavin_tx_id = json.yavin_tx_id;
        }
    },
    export_as_JSON() {
        const result = super.export_as_JSON(...arguments);
        if (result && this.payment_method?.use_payment_terminal === 'yavin') {
            return Object.assign(result, {
                yavin_issuer: this.yavin_issuer,
                yavin_attempt_number: this.yavin_attempt_number,
                yavin_payment_request_time: this.yavin_payment_request_time,
                yavin_original_transaction_id: this.yavin_original_transaction_id,
                yavin_last_failure_type: this.yavin_last_failure_type,
                yavin_last_reversal_failure_type: this.yavin_last_reversal_failure_type,
                yavin_abort_state: this.yavin_abort_state,
                yavin_operation_type: this.yavin_operation_type,
                yavin_tx_id: this.yavin_tx_id,
            });
        }
        return result;
    },
    handle_payment_response(isPaymentSuccessful) {
        if (this.payment_method?.use_payment_terminal === 'yavin' && this.yavin_preserve_status) {
            delete this.yavin_preserve_status;
            if (
                isPaymentSuccessful &&
                this.payment_method.payment_terminal?.supports_reversals
            ) {
                this.can_be_reversed = true;
            }
            return isPaymentSuccessful;
        }
        return super.handle_payment_response(...arguments);
    },
});
