/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import {
    YAVIN_OPERATION_REVERSAL,
    getYavinOperationType,
    setYavinPaymentStatus,
} from "./lifecycle_utils";

const YAVIN_REVERSAL_TIMEOUT_MS_FALLBACK = 62000;

export async function executePaymentReversal(cid, initialTransactionId = null, options = {}) {
    const order = this.pos.get_order();
    const pay_line = order.get_paymentlines().find((line) => line.cid === cid);

    if (!pay_line) {
        return false;
    }
    const isInProgress = this._is_line_request_in_progress(pay_line);
    if (isInProgress) {
        const isRefundFlow = !!pay_line.yavin_original_transaction_id;
        if (!isRefundFlow) {
            this._show_error(_t("A payment request is already being processed. Please wait."));
            return false;
        }
    }

    const payment_status = pay_line.get_payment_status();
    const isReversalRecovery = getYavinOperationType(pay_line) === YAVIN_OPERATION_REVERSAL;
    const hasOriginalTxId = !!initialTransactionId || !!pay_line.yavin_original_transaction_id;

    if (!hasOriginalTxId && !isReversalRecovery && payment_status !== "done") {
        return false;
    }

    const transaction_id =
        initialTransactionId || pay_line.yavin_original_transaction_id || pay_line.transaction_id;

    if (!transaction_id) {
        this._show_error(_t("Cannot reverse payment: missing transaction ID."));
        return false;
    }

    this._set_line_request_in_progress(pay_line, true);
    this._set_operation_type(pay_line, YAVIN_OPERATION_REVERSAL);
    pay_line.yavin_payment_request_time = Date.now();
    setYavinPaymentStatus(pay_line, "waitingCard");

    try {
        const timeout =
            this.payment_method.yavin_reversal_timeout_ms || YAVIN_REVERSAL_TIMEOUT_MS_FALLBACK;

        const lastReversalFailureType = pay_line.yavin_last_reversal_failure_type;
        if (lastReversalFailureType === "failure") {
            this._increment_attempt_number(pay_line);
            pay_line.yavin_last_reversal_failure_type = null;
        }

        if (pay_line.yavin_attempt_number === undefined) {
            pay_line.yavin_attempt_number = 1;
        }

        const data = {
            amount: pay_line.amount,
            currency_id: this.pos.currency.id,
            payment_method_id: this.payment_method.id,
            payment_id: cid,
            initial_transaction_id: transaction_id,
            timeout,
            order_uid: order.uid || "",
            partner_id: order.partner ? order.partner.id : null,
            session_id: order.pos_session_id || null,
            attempt_number: pay_line.yavin_attempt_number,
        };

        const response = await this.env.services.orm.silent.call(
            "pos.payment.method",
            "yavin_send_reversal",
            [data]
        );
        const operationStatus = this._getOperationStatus(response);

        if (operationStatus) {
            if (operationStatus === "success") {
                if (pay_line.amount < 0) {
                    setYavinPaymentStatus(pay_line, "done");
                } else {
                    pay_line.set_amount(0);
                    setYavinPaymentStatus(pay_line, "reversed");
                }

                if (this._is_abort_pending(pay_line)) {
                    this._clear_abort_state(pay_line);
                }
                this._clear_operation_type(pay_line);
                pay_line.yavin_last_reversal_failure_type = null;
                return true;
            }

            if (this._is_abort_pending(pay_line)) {
                this._ensure_next_attempt_after_abort(pay_line);
                this._clear_operation_type(pay_line);
                return false;
            }

            if (operationStatus === "network_error" || operationStatus === "timeout") {
                pay_line.yavin_last_reversal_failure_type = operationStatus;
            } else {
                pay_line.yavin_last_reversal_failure_type = "failure";
            }
            const error_msg = response.error_message || _t("The reversal transaction has failed.");
            if (!options.silentError) {
                this._show_error(error_msg);
            }
            return false;
        }

        return false;
    } catch (error) {
        if (this._is_abort_pending(pay_line)) {
            this._ensure_next_attempt_after_abort(pay_line);
            return false;
        }

        pay_line.yavin_last_reversal_failure_type = "timeout";
        if (!options.silentError) {
            this._handle_error(_t("No answer from the payment terminal in the given time."));
        }
        return false;
    } finally {
        this._set_line_request_in_progress(pay_line, false);
    }
}
