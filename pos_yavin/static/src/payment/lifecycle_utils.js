/** @odoo-module */

export const YAVIN_RECOVERY_WINDOW_MS_FALLBACK = 124000;
export const YAVIN_BLOCKING_STATUSES = [
    "waitingCard",
    "waiting",
    "waitingCancel",
    "waitingCapture",
    "reversing",
];
export const YAVIN_RECOVERABLE_STATUSES = ["retry", ...YAVIN_BLOCKING_STATUSES];
export const YAVIN_OPERATION_PAYMENT = "payment";
export const YAVIN_OPERATION_REVERSAL = "reversal";
export const YAVIN_STATUS_NEW = "new";

export function isYavinPaymentLine(line) {
    return line?.payment_method?.use_payment_terminal === "yavin";
}

export function isYavinBlockingStatus(status) {
    return YAVIN_BLOCKING_STATUSES.includes(status);
}

export function isYavinRecoverableStatus(status) {
    return YAVIN_RECOVERABLE_STATUSES.includes(status);
}

export function getYavinRecoveryWindowMs(line) {
    return line?.payment_method?.yavin_timeout_ms || YAVIN_RECOVERY_WINDOW_MS_FALLBACK;
}

export function isYavinRecentRequest(line, now = Date.now()) {
    const requestTime = line?.yavin_payment_request_time || 0;
    return Boolean(requestTime) && now - requestTime < getYavinRecoveryWindowMs(line);
}

export function getYavinOperationType(line) {
    return line?.yavin_operation_type || YAVIN_OPERATION_PAYMENT;
}

export function getYavinStaleStatus(line) {
    const operationType = getYavinOperationType(line);
    if (
        operationType === YAVIN_OPERATION_REVERSAL &&
        line?.amount >= 0 &&
        !line?.yavin_original_transaction_id
    ) {
        return "done";
    }
    return "retry";
}

export function shouldRecoverYavinLine(line, now = Date.now()) {
    if (!isYavinPaymentLine(line) || !line?.yavin_attempt_number) {
        return false;
    }
    const status = line.get_payment_status();
    return isYavinRecoverableStatus(status) && isYavinRecentRequest(line, now);
}

export function normalizeYavinStatus(status) {
    return status || YAVIN_STATUS_NEW;
}

export function canTransitionYavinStatus(fromStatus, toStatus) {
    const from = normalizeYavinStatus(fromStatus);
    if (from === toStatus) {
        return true;
    }
    if (from === "reversed" && YAVIN_BLOCKING_STATUSES.includes(toStatus)) {
        return false;
    }
    if (from === "done" && YAVIN_BLOCKING_STATUSES.includes(toStatus) && toStatus !== "reversing") {
        return false;
    }
    if (from === YAVIN_STATUS_NEW && (toStatus === "reversing" || toStatus === "waitingCancel")) {
        return false;
    }
    if (
        ["waitingCard", "waiting", "waitingCapture", "waitingCancel"].includes(from) &&
        toStatus === "reversing"
    ) {
        return false;
    }
    return true;
}

export function setYavinPaymentStatus(line, status, options = {}) {
    if (!line || !status) {
        return false;
    }
    const force = options.force === true;
    const currentStatus = normalizeYavinStatus(line.get_payment_status?.());
    if (!force && !canTransitionYavinStatus(currentStatus, status)) {
        return false;
    }
    line.set_payment_status(status);
    return true;
}
