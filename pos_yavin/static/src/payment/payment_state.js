/** @odoo-module */

import {
    YAVIN_OPERATION_REVERSAL,
    getYavinOperationType,
    getYavinStaleStatus,
    setYavinPaymentStatus,
} from "./lifecycle_utils";

export function setStatusAndPreserve(pay_line, status) {
    setYavinPaymentStatus(pay_line, status, { force: true });
    pay_line.yavin_preserve_status = true;
}

export function incrementAttemptNumber(pay_line) {
    if (!pay_line) return 1;
    if (pay_line.yavin_attempt_number === undefined) {
        pay_line.yavin_attempt_number = 1;
    }
    pay_line.yavin_attempt_number += 1;
    return pay_line.yavin_attempt_number;
}

export function isLineRequestInProgress(pay_line) {
    return !!pay_line?.yavin_request_in_progress;
}

export function setLineRequestInProgress(pay_line, inProgress) {
    if (pay_line) {
        pay_line.yavin_request_in_progress = inProgress;
    }
}

export function setOperationType(pay_line, operationType) {
    if (pay_line) {
        pay_line.yavin_operation_type = operationType;
    }
}

export function clearOperationType(pay_line) {
    if (pay_line) {
        pay_line.yavin_operation_type = null;
    }
}

export function getAbortState(pay_line) {
    return pay_line?.yavin_abort_state || null;
}

export function isAbortPending(pay_line) {
    return ["requested", "confirmed"].includes(getAbortState(pay_line));
}

export function markAbortRequested(pay_line) {
    if (pay_line) {
        pay_line.yavin_abort_state = "requested";
    }
}

export function markAbortConfirmed(pay_line) {
    if (!pay_line) {
        return;
    }
    incrementAttemptNumber(pay_line);
    pay_line.yavin_abort_state = "confirmed";
}

export function clearAbortState(pay_line) {
    if (pay_line) {
        pay_line.yavin_abort_state = null;
    }
}

export function ensureNextAttemptAfterAbort(pay_line) {
    if (!pay_line) {
        return;
    }
    if (getAbortState(pay_line) === "requested") {
        incrementAttemptNumber(pay_line);
    }
    pay_line.yavin_abort_state = null;
}

export function resetStaleLine(pay_line, paymentYavin) {
    if (!pay_line) {
        return;
    }
    clearAbortState(pay_line);
    setLineRequestInProgress(pay_line, false);
    const staleStatus = getYavinStaleStatus(pay_line);
    setYavinPaymentStatus(pay_line, staleStatus, { force: true });
    if (staleStatus === "done") {
        pay_line.can_be_reversed = paymentYavin.supports_reversals;
        clearOperationType(pay_line);
    }
}

export function recoverPendingLine(pay_line, paymentYavin) {
    const operationType = getYavinOperationType(pay_line);
    if (operationType === YAVIN_OPERATION_REVERSAL) {
        return paymentYavin.send_payment_reversal(
            pay_line.cid,
            pay_line.yavin_original_transaction_id || null,
            { silentError: true }
        );
    }
    return paymentYavin.send_payment_request(pay_line.cid, { silentError: true });
}
