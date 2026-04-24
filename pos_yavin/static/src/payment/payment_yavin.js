/** @odoo-module */
/*
    Copyright 2026 Raphaël HUCK
    @author: Raphaël HUCK
    License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
*/

import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { PaymentInterface } from "@point_of_sale/app/payment/payment_interface";
import { _t } from "@web/core/l10n/translation";
import { executePaymentCancel } from "./payment_cancel";
import {
    executePaymentRequest,
    handleYavinResponse,
    handleYavinUnexpectedResponse,
} from "./payment_request";
import { executePaymentReversal } from "./payment_reversal";
import {
    YAVIN_BLOCKING_STATUSES,
    getYavinRecoveryWindowMs,
    isYavinRecentRequest,
    shouldRecoverYavinLine,
} from "./lifecycle_utils";
import {
    clearAbortState,
    clearOperationType,
    ensureNextAttemptAfterAbort,
    getAbortState,
    incrementAttemptNumber,
    isAbortPending,
    isLineRequestInProgress,
    markAbortConfirmed,
    markAbortRequested,
    recoverPendingLine,
    resetStaleLine,
    setLineRequestInProgress,
    setOperationType,
    setStatusAndPreserve,
} from "./payment_state";

export class PaymentYavin extends PaymentInterface {
    setup() {
        super.setup(...arguments);
        this.enable_reversals();

    }

    _set_status_and_preserve(pay_line, status) {
        return setStatusAndPreserve(pay_line, status);
    }


    _increment_attempt_number(pay_line) {
        return incrementAttemptNumber(pay_line);
    }

    _is_line_request_in_progress(pay_line) {
        return isLineRequestInProgress(pay_line);
    }

    _set_line_request_in_progress(pay_line, inProgress) {
        return setLineRequestInProgress(pay_line, inProgress);
    }

    _set_operation_type(pay_line, operationType) {
        return setOperationType(pay_line, operationType);
    }

    _clear_operation_type(pay_line) {
        return clearOperationType(pay_line);
    }

    _reset_stale_line(pay_line) {
        return resetStaleLine(pay_line, this);
    }

    _recover_pending_line(pay_line) {
        return recoverPendingLine(pay_line, this);
    }

    _get_abort_state(pay_line) {
        return getAbortState(pay_line);
    }

    _is_abort_pending(pay_line) {
        return isAbortPending(pay_line);
    }

    _mark_abort_requested(pay_line) {
        return markAbortRequested(pay_line);
    }

    _mark_abort_confirmed(pay_line) {
        return markAbortConfirmed(pay_line);
    }

    _clear_abort_state(pay_line) {
        return clearAbortState(pay_line);
    }

    _ensure_next_attempt_after_abort(pay_line) {
        return ensureNextAttemptAfterAbort(pay_line);
    }

    async send_payment_cancel(order, cid) {
        super.send_payment_cancel(...arguments);
        return executePaymentCancel.call(this, order, cid);
    }

    async _handle_yavin_response(pay_line, response = {}, options = {}) {
        return handleYavinResponse.call(this, pay_line, response, options);
    }

    _handle_yavin_unexpected_response(pay_line) {
        return handleYavinUnexpectedResponse.call(this, pay_line);
    }

    async send_payment_reversal(cid, initialTransactionId = null, options = {}) {
        await super.send_payment_reversal(...arguments);
        return executePaymentReversal.call(this, cid, initialTransactionId, options);
    }

    async send_payment_request(cid, options = {}) {
        await super.send_payment_request(...arguments);
        return executePaymentRequest.call(this, cid, options);
    }

    _handle_error(msg) {
        this._show_error(msg);
        return false;
    }

    _isObjectResponse(response, key) {
        return Boolean(response) && typeof response === "object" && key in response;
    }

    _getOperationStatus(response) {
        if (!this._isObjectResponse(response, "operation_status")) {
            return null;
        }
        return response.operation_status;
    }

    _show_error(msg, title) {
        this.env.services.popup.add(ErrorPopup, {
            title: title || _t("Payment Terminal Error"),
            body: msg,
        });
    }

    check_pending_transactions(order = this.pos.get_order()) {
        if (!order) {
            return;
        }

        const now = Date.now();
        for (const pay_line of order.get_paymentlines()) {
            if (pay_line?.payment_method?.id !== this.payment_method.id) {
                continue;
            }
            if (shouldRecoverYavinLine(pay_line, now)) {
                this._recover_pending_line(pay_line);
                continue;
            }
            const status = pay_line.get_payment_status();
            if (
                YAVIN_BLOCKING_STATUSES.includes(status) &&
                (pay_line.yavin_payment_request_time === 0 ||
                    !isYavinRecentRequest(pay_line, now) ||
                    now - pay_line.yavin_payment_request_time >= getYavinRecoveryWindowMs(pay_line))
            ) {
                this._reset_stale_line(pay_line);
            }
        }
    }
}
