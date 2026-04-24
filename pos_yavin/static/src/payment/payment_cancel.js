/** @odoo-module */

import { _t } from "@web/core/l10n/translation";

export async function executePaymentCancel(order, cid) {
    // We expect a failure because we are cancelling.
    // Set it immediately to handle race condition where payment response
    // arrives before the abort response.
    const order_uid = order.uid || "";
    const pay_line = order.get_paymentlines().find((line) => line.cid === cid);
    this._mark_abort_requested(pay_line);

    // Optimize abort timing: wait if abort is sent too soon after payment request
    // This gives the terminal time to initialize the transaction, reducing retries
    if (pay_line && pay_line.yavin_payment_request_time) {
        const time_since_request = Date.now() - pay_line.yavin_payment_request_time;
        const MIN_ABORT_DELAY_MS = 2000; // 2 seconds minimum delay
        if (time_since_request < MIN_ABORT_DELAY_MS) {
            const wait_time = MIN_ABORT_DELAY_MS - time_since_request;
            await new Promise((resolve) => setTimeout(resolve, wait_time));
        }
    }

    const attempt_number =
        pay_line && pay_line.yavin_attempt_number !== undefined
            ? pay_line.yavin_attempt_number
            : 1;

    const data = {
        payment_method_id: this.payment_method.id,
        order_uid,
        payment_id: cid,
        attempt_number,
    };

    try {
        const response = await this.env.services.orm.silent.call(
            "pos.payment.method",
            "yavin_abort_payment",
            [data]
        );
        const operationStatus = this._getOperationStatus(response);
        if (operationStatus === "success") {
            if (pay_line) {
                this._mark_abort_confirmed(pay_line);

                // We do NOT unlock the UI here. We wait for the actual payment response (which will be a failure)
                // to arrive and unlock it naturally. This prevents race conditions and double clicks.
                return true;
            }
            return true;
        }

        const errorMessage =
            response.error_message ||
            _t("Failed to abort payment. Please cancel it manually on the payment terminal.");
        this._show_error(errorMessage);
        // Abort failed, so we are not legitimately waiting for a failure anymore.
        // If the payment fails later (timeout), it's a real error.
        this._clear_abort_state(pay_line);
        return false;
    } catch {
        // We don't reset the flag here because a timeout/network error on abort
        // doesn't mean the abort didn't reach the terminal. It might still cancel.
        return false;
    }
}
