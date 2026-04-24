/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { YavinTipHandler } from "./tip_handler";
import {
    YAVIN_OPERATION_PAYMENT,
    YAVIN_OPERATION_REVERSAL,
    setYavinPaymentStatus,
} from "./lifecycle_utils";

const YAVIN_DEFAULT_TIMEOUT_MS_FALLBACK = 124000;

export async function handleYavinResponse(pay_line, response = {}, options = {}) {
    const operationStatus = response.operation_status || "issue";

    if (!pay_line) {
        return false;
    }

    const handleFailure = (skipError = false, failureType = "failure") => {
        setYavinPaymentStatus(pay_line, "retry");
        pay_line.yavin_last_failure_type = failureType;
        if (skipError || options.silentError) {
            return false;
        }
        const error_msg = response.error_message || _t("The payment transaction has failed.");
        return this._handle_error(error_msg);
    };

    if (operationStatus === "success") {
        setYavinPaymentStatus(pay_line, "done");
        pay_line.can_be_reversed = this.supports_reversals;
        this._clear_operation_type(pay_line);

        pay_line.card_type = response.card_type;
        pay_line.yavin_issuer = response.yavin_issuer;
        pay_line.transaction_id = response.transaction_id;
        if ("ticket" in response) {
            pay_line.set_receipt_info(response.ticket);
        }

        if (response.gift_amount && response.gift_amount > 0) {
            await YavinTipHandler.handleTipFromResponse({
                order: pay_line.order,
                pay_line,
                gift_amount: response.gift_amount,
                pos: this.pos,
                env: this.env,
                yavinPaymentMethod: this.payment_method,
            });
        }

        this._increment_attempt_number(pay_line);

        if (this._is_abort_pending(pay_line)) {
            this._clear_abort_state(pay_line);
        }
        return true;
    }

    if (operationStatus === "failure") {
        if (this._is_abort_pending(pay_line)) {
            this._ensure_next_attempt_after_abort(pay_line);
            setYavinPaymentStatus(pay_line, "retry");
            return false;
        }
        return handleFailure(false, "failure");
    }

    if (operationStatus === "network_error" || operationStatus === "timeout") {
        setYavinPaymentStatus(pay_line, "retry");
        pay_line.yavin_last_failure_type = operationStatus;
        const error_msg =
            response.error_message ||
            (operationStatus === "network_error"
                ? _t("Cannot connect to payment terminal. Please check the network connection.")
                : _t("Payment terminal did not respond. Please try again."));
        return this._handle_error(error_msg);
    }

    if (operationStatus === "issue") {
        if (this._is_abort_pending(pay_line)) {
            this._clear_abort_state(pay_line);
            return handleFailure(true, "failure");
        }
        this._clear_operation_type(pay_line);
        this._set_status_and_preserve(pay_line, "force_done");
        return this._handle_error(response.error_message || _t("The payment transaction has failed."));
    }

    if (this._is_abort_pending(pay_line)) {
        this._clear_abort_state(pay_line);
        return handleFailure(true, "failure");
    }
    return handleFailure(false, "failure");
}

export function handleYavinUnexpectedResponse(pay_line) {
    this._clear_operation_type(pay_line);
    this._set_status_and_preserve(pay_line, "force_done");

    if (this._is_abort_pending(pay_line)) {
        this._clear_abort_state(pay_line);
        return Promise.resolve(false);
    }

    return Promise.reject();
}

const YAVIN_CLOUD_POLL_MS = 1000;

/**
 * Cloud payment: short ``yavin_cloud_start`` RPC then poll ``yavin_cloud_status`` until
 * terminal result (avoids holding one HTTP worker for the full webhook window).
 */
async function executeCloudPaymentRequest(pay_line, data, options, timeout) {
    const pmId = this.payment_method.id;
    let startResp;
    try {
        startResp = await this.env.services.orm.silent.call(
            "pos.payment.method",
            "yavin_cloud_start",
            [data],
        );
    } catch (error) {
        throw error;
    }

    const startStatus = this._getOperationStatus(startResp);
    if (!startStatus) {
        return this._handle_yavin_unexpected_response(pay_line);
    }
    if (startStatus !== "pending") {
        startResp.operation_status = startStatus;
        return await this._handle_yavin_response(pay_line, startResp, options);
    }

    if (startResp.yavin_tx_id == null) {
        return this._handle_yavin_unexpected_response(pay_line);
    }
    pay_line.yavin_tx_id = startResp.yavin_tx_id;

    const deadline = Date.now() + timeout;

    while (Date.now() < deadline) {
        if (this._is_abort_pending(pay_line)) {
            return false;
        }
        let statusResp;
        try {
            statusResp = await this.env.services.orm.silent.call(
                "pos.payment.method",
                "yavin_cloud_status",
                [
                    {
                        yavin_tx_id: pay_line.yavin_tx_id,
                        payment_method_id: pmId,
                        expire: false,
                    },
                ],
            );
        } catch (error) {
            await new Promise((resolve) => setTimeout(resolve, YAVIN_CLOUD_POLL_MS));
            continue;
        }

        const op = this._getOperationStatus(statusResp);
        if (!op) {
            await new Promise((resolve) => setTimeout(resolve, YAVIN_CLOUD_POLL_MS));
            continue;
        }
        if (op === "pending") {
            await new Promise((resolve) => setTimeout(resolve, YAVIN_CLOUD_POLL_MS));
            continue;
        }
        statusResp.operation_status = op;
        return await this._handle_yavin_response(pay_line, statusResp, options);
    }

    let finalResp;
    try {
        finalResp = await this.env.services.orm.silent.call(
            "pos.payment.method",
            "yavin_cloud_status",
            [
                {
                    yavin_tx_id: pay_line.yavin_tx_id,
                    payment_method_id: pmId,
                    expire: true,
                },
            ],
        );
    } catch (error) {
        throw error;
    }
    const finalOp = this._getOperationStatus(finalResp);
    if (finalOp) {
        finalResp.operation_status = finalOp;
    }
    return await this._handle_yavin_response(pay_line, finalResp, options);
}

export async function executePaymentRequest(cid, options = {}) {
    const order = this.pos.get_order();
    const pay_line = order?.get_paymentline ? order.get_paymentline(cid) : order?.selected_paymentline;

    if (!pay_line) {
        return false;
    }

    if (pay_line.yavin_original_transaction_id) {
        const originalTransactionId = pay_line.yavin_original_transaction_id;
        this._set_line_request_in_progress(pay_line, true);
        this._set_operation_type(pay_line, YAVIN_OPERATION_REVERSAL);
        return await this.send_payment_reversal(cid, originalTransactionId);
    }

    if (this._is_line_request_in_progress(pay_line)) {
        this._show_error(_t("A payment request is already being processed. Please wait."));
        return false;
    }

    if (pay_line.amount < 0) {
        this._show_error(
            _t(
                "Cannot process standalone refund with Yavin. Please use the 'Refund' button on the original order to link to the original transaction."
            )
        );
        setYavinPaymentStatus(pay_line, "retry");
        return false;
    }

    this._set_line_request_in_progress(pay_line, true);
    this._set_operation_type(pay_line, YAVIN_OPERATION_PAYMENT);

    const lastFailureType = pay_line.yavin_last_failure_type;
    if (lastFailureType === "failure") {
        this._increment_attempt_number(pay_line);
        pay_line.yavin_last_failure_type = null;
    }

    pay_line.yavin_payment_request_time = Date.now();
    setYavinPaymentStatus(pay_line, "waitingCard");

    try {
        const timeout = this.payment_method.yavin_timeout_ms || YAVIN_DEFAULT_TIMEOUT_MS_FALLBACK;
        if (pay_line.yavin_attempt_number === undefined) {
            pay_line.yavin_attempt_number = 1;
        }

        const cashier = this.pos.get_cashier();
        const data = {
            amount: pay_line.amount,
            currency_id: this.pos.currency.id,
            payment_method_id: this.payment_method.id,
            payment_id: cid,
            timeout,
            order_uid: order.uid || "",
            partner_id: order.partner ? order.partner.id : null,
            session_id: order.pos_session_id || null,
            attempt_number: pay_line.yavin_attempt_number,
            cashier_name: cashier ? cashier.name : "",
        };

        if (this.payment_method.yavin_effective_connection_mode === "cloud") {
            return await executeCloudPaymentRequest.call(
                this,
                pay_line,
                data,
                options,
                timeout,
            );
        }

        const response = await this.env.services.orm.silent.call("pos.payment.method", "yavin_send_payment", [
            data,
        ]);

        const operationStatus = this._getOperationStatus(response);
        if (operationStatus) {
            response.operation_status = operationStatus;
            return await this._handle_yavin_response(pay_line, response, options);
        }
        return this._handle_yavin_unexpected_response(pay_line);
    } catch (error) {
        if (pay_line.yavin_attempt_number === undefined) {
            pay_line.yavin_attempt_number = 1;
        }
        setYavinPaymentStatus(pay_line, "retry");
        pay_line.yavin_last_failure_type = "timeout";

        if (this._is_abort_pending(pay_line)) {
            this._clear_abort_state(pay_line);
            return false;
        }

        if (options.silentError) {
            return false;
        }

        return this._handle_error(_t("No answer from the payment terminal in the given time."));
    } finally {
        if (!this._is_abort_pending(pay_line)) {
            const final_status = pay_line.get_payment_status();
            if (["waitingCard", "waiting", "waitingCancel", "waitingCapture"].includes(final_status)) {
                setYavinPaymentStatus(pay_line, "retry");
            }
        }
        this._set_line_request_in_progress(pay_line, false);
    }
}
