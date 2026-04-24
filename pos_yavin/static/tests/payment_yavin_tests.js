/** @odoo-module **/

import "@pos_yavin/overrides/components/payment_screen/payment_screen";
import { PaymentYavin } from "@pos_yavin/payment/payment_yavin";
import {
    YAVIN_OPERATION_REVERSAL,
    getYavinStaleStatus,
    shouldRecoverYavinLine,
} from "@pos_yavin/payment/lifecycle_utils";
import { YavinTipHandler } from "@pos_yavin/payment/tip_handler";
import { filterYavinTipLines, shouldDisplayYavinTip } from "@pos_yavin/overrides/models/models";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patchWithCleanup } from "@web/../tests/helpers/utils";

const makeDeferred = () => {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
};

QUnit.module("pos_yavin PaymentYavin", (hooks) => {
    hooks.beforeEach(function () {
        this.rpcCalls = [];
        this.popupCalls = [];
        this.env = {
            services: {
                popup: {
                    add: (...args) => {
                        this.popupCalls.push(args);
                    },
                },
                orm: {
                    silent: {
                        call: (...args) => {
                            this.rpcCalls.push(args);
                            return Promise.resolve();
                        },
                    },
                },
            },
            utils: {},
        };
        this.pos = {
            env: this.env,
            currency: { id: 1 },
            config: { iface_tipproduct: true },
            db: {
                get_product_by_id: () => null,
                search_product: () => [],
            },
            _addProducts: () => Promise.resolve(),
            validated_orders_name_server_id_map: {},
            get_order: () => null,
            get_cashier: () => ({ name: "Administrator" }),
        };
        this.paymentMethod = {
            id: 1,
            use_payment_terminal: "yavin",
            payment_terminal: { supports_reversals: true },
            yavin_display_tip: true,
        };
        this.paymentInterface = new PaymentYavin(this.pos, this.paymentMethod);
        this.makePayLine = (overrides = {}) => {
            const payLine = {
                cid: overrides.cid || "C1",
                id: overrides.id || overrides.cid || "C1",
                payment_status: "",
                statuses: [],
                amount: overrides.amount || 5,
                order: overrides.order || {},
                payment_method: overrides.payment_method || this.paymentMethod,
                set_payment_status(status) {
                    this.payment_status = status;
                    this.statuses.push(status);
                },
                get_payment_status() {
                    return this.payment_status;
                },
                set_amount(amount) {
                    this.amount = amount;
                },
                set_receipt_info(info) {
                    this.ticket = info;
                },
            };
            return Object.assign(payLine, overrides);
        };
        this.makeOrder = (payLines = [], overrides = {}) => {
            const order = Object.assign(
                {
                    uid: "ORD-1",
                    id: "ORD-1",
                    pos_session_id: 10,
                    partner: { id: 5 },
                    selected_paymentline: payLines[0] || null,
                    finalized: false,
                    get_paymentlines() {
                        return payLines;
                    },
                    get_paymentline(cid) {
                        return payLines.find((line) => line.cid === cid);
                    },
                },
                overrides
            );
            payLines.forEach((line) => {
                line.order = order;
            });
            return order;
        };
        this.createSendContext = (options = {}) => {
            const payLine = this.makePayLine(options.payLine || {});
            const order = this.makeOrder([payLine], options.order || {});
            this.pos.get_order = () => order;
            order.selected_paymentline = payLine;
            return { payLine, order };
        };
    });

    QUnit.test("handle_yavin_response sets success metadata", async function (assert) {
        assert.expect(6);
        const payLine = this.makePayLine();
        const tipPayloads = [];
        patchWithCleanup(YavinTipHandler, {
            handleTipFromResponse: async (payload) => {
                tipPayloads.push(payload);
            }
        });
        const result = await this.paymentInterface._handle_yavin_response(payLine, {
            operation_status: "success",
            card_type: "CB",
            yavin_issuer: "Issuer",
            transaction_id: "TX-1",
            ticket: "foo",
            gift_amount: 2,
        });
        assert.ok(result);
        assert.deepEqual(payLine.statuses, ["done"]);
        assert.strictEqual(payLine.card_type, "CB");
        assert.strictEqual(payLine.transaction_id, "TX-1");
        assert.strictEqual(tipPayloads.length, 1);
        assert.strictEqual(payLine.yavin_attempt_number, 2, "attempt incremented after success");
    });

    QUnit.test("handle_yavin_response failure resets to retry", async function (assert) {
        assert.expect(4);
        const payLine = this.makePayLine();
        let capturedMessage;
        patchWithCleanup(this.paymentInterface, {
            _handle_error: (msg) => {
                capturedMessage = msg;
                return false;
            }
        });
        const result = await this.paymentInterface._handle_yavin_response(payLine, {
            operation_status: "failure",
            error_message: "Declined",
        });
        assert.notOk(result);
        assert.strictEqual(payLine.payment_status, "retry");
        assert.strictEqual(payLine.yavin_last_failure_type, "failure", "marks failure for new idempotentUuid on retry");
        assert.strictEqual(capturedMessage, "Declined");
    });

    QUnit.test("handle_yavin_response issue flags force_done", async function (assert) {
        assert.expect(2);
        const payLine = this.makePayLine();
        await this.paymentInterface._handle_yavin_response(payLine, {
            operation_status: "issue",
            error_message: "Timeout",
        });
        assert.strictEqual(payLine.payment_status, "force_done");
        assert.ok(payLine.yavin_preserve_status);
    });

    QUnit.test("handle_yavin_response timeout sets yavin_last_failure_type for technical retry", async function (assert) {
        assert.expect(3);
        const payLine = this.makePayLine();
        let capturedMessage;
        patchWithCleanup(this.paymentInterface, {
            _handle_error: (msg) => {
                capturedMessage = msg;
                return false;
            }
        });
        await this.paymentInterface._handle_yavin_response(payLine, {
            operation_status: "timeout",
            error_message: "Timed out",
        });
        assert.strictEqual(payLine.payment_status, "retry");
        assert.strictEqual(payLine.yavin_last_failure_type, "timeout");
        assert.ok(capturedMessage && capturedMessage.length > 0);
    });

    QUnit.test("handle_yavin_response failure after abort is silent", async function (assert) {
        assert.expect(4);
        const payLine = this.makePayLine();
        payLine.yavin_abort_state = "requested";
        const errorCalls = [];
        patchWithCleanup(this.paymentInterface, {
            _handle_error: (msg) => {
                errorCalls.push(msg);
                return false;
            }
        });
        const result = await this.paymentInterface._handle_yavin_response(payLine, {
            operation_status: "failure",
            error_message: "Declined",
        });
        assert.notOk(result);
        assert.strictEqual(payLine.payment_status, "retry");
        assert.deepEqual(errorCalls, []);
        assert.strictEqual(payLine.yavin_abort_state, null, "abort state reset after handling");
    });

    QUnit.test("handle_yavin_unexpected_response forces manual action", function (assert) {
        assert.expect(2);
        const payLine = this.makePayLine();
        this.paymentInterface._handle_yavin_unexpected_response(payLine).catch(() => { });
        assert.strictEqual(payLine.payment_status, "force_done");
        assert.ok(payLine.yavin_preserve_status);
    });

    QUnit.test("send_payment_request calls backend and forwards response", async function (assert) {
        assert.expect(6);
        const { payLine } = this.createSendContext({
            order: { uid: "ORD-10", partner: { id: 11 }, pos_session_id: 12 },
        });
        const rpcSpy = [];
        this.env.services.orm.silent.call = (...args) => {
            rpcSpy.push(args);
            return Promise.resolve({ operation_status: "success" });
        };
        let forwarded = null;
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async (line, response) => {
                forwarded = { line, response };
                line.set_payment_status("done");
                // Increment attempt_number like the real code does
                if (line.yavin_attempt_number === undefined) {
                    line.yavin_attempt_number = 1;
                }
                line.yavin_attempt_number += 1;
                return true;
            }
        });
        const result = await this.paymentInterface.send_payment_request(payLine.cid);
        assert.ok(result);
        assert.strictEqual(payLine.statuses[0], "waitingCard");
        assert.deepEqual(forwarded.line, payLine);
        assert.strictEqual(forwarded.response.operation_status, "success");
        assert.strictEqual(payLine.yavin_attempt_number, 2);
        const dataPayload = rpcSpy[0][2][0];
        assert.deepEqual(
            {
                currency_id: dataPayload.currency_id,
                payment_method_id: dataPayload.payment_method_id,
                order_uid: dataPayload.order_uid,
                partner_id: dataPayload.partner_id,
                session_id: dataPayload.session_id,
                attempt_number: dataPayload.attempt_number,
            },
            {
                currency_id: 1,
                payment_method_id: this.paymentMethod.id,
                order_uid: "ORD-10",
                partner_id: 11,
                session_id: 12,
                attempt_number: 1,
            }
        );
        // assert.notOk(this.paymentInterface._payment_request_in_progress);
    });

    QUnit.test("send_payment_request accepts canonical operation_status", async function (assert) {
        assert.expect(2);
        const { payLine } = this.createSendContext();
        let forwardedStatus = null;
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async (line, response) => {
                forwardedStatus = response.operation_status;
                line.set_payment_status("done");
                return true;
            }
        });
        this.env.services.orm.silent.call = () =>
            Promise.resolve({ operation_status: "success" });

        const result = await this.paymentInterface.send_payment_request(payLine.cid);

        assert.ok(result);
        assert.strictEqual(forwardedStatus, "success");
    });

    QUnit.test("send_payment_request blocks concurrent invocations", async function (assert) {
        assert.expect(3);
        const { payLine } = this.createSendContext();
        const deferred = makeDeferred();
        this.env.services.orm.silent.call = () => deferred.promise;
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async () => true
        });
        const firstPromise = this.paymentInterface.send_payment_request(payLine.cid);
        let errorMessage = null;
        patchWithCleanup(this.paymentInterface, {
            _show_error: (msg) => {
                errorMessage = msg;
            }
        });
        const blocked = await this.paymentInterface.send_payment_request(payLine.cid);
        assert.notOk(blocked, "second call returns false");
        assert.ok(errorMessage && errorMessage.includes("already being processed"));
        deferred.resolve({ operation_status: "success" });
        await firstPromise;
        assert.strictEqual(payLine.statuses[0], "waitingCard");
    });

    QUnit.test("send_payment_request allows another line while one line is pending", async function (assert) {
        assert.expect(4);
        const firstLine = this.makePayLine({ cid: "FIRST" });
        const secondLine = this.makePayLine({ cid: "SECOND" });
        const order = this.makeOrder([firstLine, secondLine], { selected_paymentline: secondLine });
        this.pos.get_order = () => order;

        const deferred = makeDeferred();
        const payloads = [];
        this.env.services.orm.silent.call = (...args) => {
            const payload = args[2][0];
            payloads.push(payload);
            if (payload.payment_id === "FIRST") {
                return deferred.promise;
            }
            return Promise.resolve({ operation_status: "success", transaction_id: "TX-SECOND" });
        };
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async (line) => {
                line.set_payment_status("done");
                return true;
            }
        });

        const firstPromise = this.paymentInterface.send_payment_request("FIRST");
        const secondResult = await this.paymentInterface.send_payment_request("SECOND");

        assert.ok(secondResult, "other line is not blocked");
        assert.strictEqual(payloads.length, 2, "both backend calls were sent");
        assert.strictEqual(secondLine.payment_status, "done", "second line completed normally");

        deferred.resolve({ operation_status: "success", transaction_id: "TX-FIRST" });
        await firstPromise;
        assert.notOk(firstLine.yavin_request_in_progress, "first line lock released at the end");
    });

    QUnit.test("send_payment_request validation failure releases no line lock", async function (assert) {
        assert.expect(3);
        const { payLine } = this.createSendContext({
            payLine: { amount: -5 },
        });
        let errorMessage = null;
        patchWithCleanup(this.paymentInterface, {
            _show_error: (msg) => {
                errorMessage = msg;
            }
        });

        const result = await this.paymentInterface.send_payment_request(payLine.cid);

        assert.notOk(result);
        assert.notOk(payLine.yavin_request_in_progress, "line lock is not left behind");
        assert.ok(errorMessage && errorMessage.includes("standalone refund"));
    });

    QUnit.test("send_payment_request handles timeout with retry", async function (assert) {
        assert.expect(5);
        const { payLine } = this.createSendContext();
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async () => true
        });
        let errorMessage;
        patchWithCleanup(this.paymentInterface, {
            _handle_error: (msg) => {
                errorMessage = msg;
                return false;
            }
        });
        this.env.services.orm.silent.call = () => Promise.reject(new Error("timeout"));
        const result = await this.paymentInterface.send_payment_request(payLine.cid);
        assert.notOk(result);
        assert.strictEqual(payLine.payment_status, "retry");
        // attempt_number should NOT be incremented on timeout (technical retry: same idempotentUuid)
        assert.strictEqual(payLine.yavin_attempt_number, 1);
        assert.strictEqual(payLine.yavin_last_failure_type, "timeout");
        assert.ok(errorMessage.includes("No answer"));
    });

    QUnit.test("send_payment_request retry after failure (ko) uses new idempotentUuid", async function (assert) {
        assert.expect(3);
        const { payLine } = this.createSendContext();
        payLine.set_payment_status("retry");
        payLine.yavin_last_failure_type = "failure";
        payLine.yavin_attempt_number = 1;

        const rpcPayloads = [];
        this.env.services.orm.silent.call = (...args) => {
            rpcPayloads.push(args[2][0]);
            return Promise.resolve({ operation_status: "success", transaction_id: "TX-2" });
        };
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async () => true
        });

        await this.paymentInterface.send_payment_request(payLine.cid);

        // After failure (ko), retry must increment attempt_number for new idempotentUuid
        assert.strictEqual(payLine.yavin_attempt_number, 2);
        assert.strictEqual(rpcPayloads[0].attempt_number, 2);
        assert.strictEqual(payLine.yavin_last_failure_type, null, "reset after increment");
    });

    QUnit.test("send_payment_request retry after failure still increments when Odoo set waiting", async function (assert) {
        assert.expect(3);
        const { payLine } = this.createSendContext();
        // This reproduces the real Odoo flow: pay() already changed the line to "waiting"
        // before send_payment_request() is called.
        payLine.set_payment_status("waiting");
        payLine.yavin_last_failure_type = "failure";
        payLine.yavin_attempt_number = 1;

        let attemptInPayload;
        this.env.services.orm.silent.call = (...args) => {
            attemptInPayload = args[2][0].attempt_number;
            return Promise.resolve({ operation_status: "success", transaction_id: "TX-2B" });
        };
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async () => true
        });

        await this.paymentInterface.send_payment_request(payLine.cid);

        assert.strictEqual(payLine.yavin_attempt_number, 2);
        assert.strictEqual(attemptInPayload, 2);
        assert.strictEqual(payLine.yavin_last_failure_type, null, "reset after increment");
    });

    QUnit.test("send_payment_request uses clicked line instead of selected line", async function (assert) {
        assert.expect(3);
        const targetLine = this.makePayLine({ cid: "TARGET", yavin_attempt_number: 1 });
        targetLine.yavin_last_failure_type = "failure";
        const selectedLine = this.makePayLine({ cid: "OTHER", yavin_attempt_number: 1 });
        const order = this.makeOrder([targetLine, selectedLine], { selected_paymentline: selectedLine });
        this.pos.get_order = () => order;

        let rpcPayload;
        this.env.services.orm.silent.call = (...args) => {
            rpcPayload = args[2][0];
            return Promise.resolve({ operation_status: "success", transaction_id: "TX-CID" });
        };
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async () => true
        });

        await this.paymentInterface.send_payment_request("TARGET");

        assert.strictEqual(targetLine.yavin_attempt_number, 2, "clicked line incremented");
        assert.strictEqual(selectedLine.yavin_attempt_number, 1, "selected line untouched");
        assert.strictEqual(rpcPayload.attempt_number, 2, "payload uses clicked line attempt");
    });

    QUnit.test("send_payment_request technical retry after timeout keeps same idempotentUuid", async function (assert) {
        assert.expect(2);
        const { payLine } = this.createSendContext();
        payLine.set_payment_status("retry");
        payLine.yavin_last_failure_type = "timeout";
        payLine.yavin_attempt_number = 1;

        const rpcPayloads = [];
        this.env.services.orm.silent.call = (...args) => {
            rpcPayloads.push(args[2][0]);
            return Promise.resolve({ operation_status: "success", transaction_id: "TX-3" });
        };
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async () => true
        });

        await this.paymentInterface.send_payment_request(payLine.cid);

        // Technical retry (timeout): same idempotentUuid, no increment
        assert.strictEqual(payLine.yavin_attempt_number, 1);
        assert.strictEqual(rpcPayloads[0].attempt_number, 1);
    });

    QUnit.test("send_payment_request technical retry after network_error keeps same idempotentUuid", async function (assert) {
        assert.expect(2);
        const { payLine } = this.createSendContext();
        payLine.set_payment_status("retry");
        payLine.yavin_last_failure_type = "network_error";
        payLine.yavin_attempt_number = 1;

        let attemptInPayload;
        this.env.services.orm.silent.call = (...args) => {
            attemptInPayload = args[2][0].attempt_number;
            return Promise.resolve({ operation_status: "success", transaction_id: "TX-4" });
        };
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async () => true
        });

        await this.paymentInterface.send_payment_request(payLine.cid);

        // Technical retry (network_error): same idempotentUuid, no increment
        assert.strictEqual(payLine.yavin_attempt_number, 1);
        assert.strictEqual(attemptInPayload, 1);
    });

    QUnit.test("send_payment_request resets waiting status in finally", async function (assert) {
        assert.expect(2);
        const { payLine } = this.createSendContext();
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async (line) => {
                line.set_payment_status("waitingCard");
                return false;
            }
        });
        this.env.services.orm.silent.call = () =>
            Promise.resolve({ operation_status: "failure", error_message: "Declined" });
        await this.paymentInterface.send_payment_request(payLine.cid);
        assert.strictEqual(
            payLine.payment_status,
            "retry",
            "finally block resets lingering waiting statuses"
        );
        assert.strictEqual(payLine.statuses[0], "waitingCard");
    });

    QUnit.test("send_payment_cancel uses current attempt for abort and increments after success", async function (assert) {
        assert.expect(7);
        const payLine = this.makePayLine({ cid: "C42", yavin_attempt_number: 1 });
        const order = this.makeOrder([payLine], { uid: "ORD-ABORT" });
        const rpcArgs = [];
        this.env.services.orm.silent.call = (...args) => {
            rpcArgs.push(args);
            return Promise.resolve({ operation_status: "success" });
        };
        const result = await this.paymentInterface.send_payment_cancel(order, "C42");
        assert.ok(result);
        assert.strictEqual(payLine.yavin_abort_state, "confirmed");
        assert.strictEqual(
            rpcArgs[0][2][0].attempt_number,
            1,
            "abort uses current attempt_number/idempotentUuid"
        );
        assert.strictEqual(payLine.yavin_attempt_number, 2);
        assert.strictEqual(payLine.yavin_abort_state, "confirmed", "abort state marked as confirmed");
        assert.strictEqual(rpcArgs[0][2][0].payment_id, "C42");
        assert.strictEqual(rpcArgs[0][2][0].order_uid, "ORD-ABORT");
    });

    QUnit.test("send_payment_cancel accepts canonical operation_status", async function (assert) {
        assert.expect(2);
        const payLine = this.makePayLine({ cid: "C43", yavin_attempt_number: 1 });
        const order = this.makeOrder([payLine], { uid: "ORD-ABORT-CANONICAL" });
        this.env.services.orm.silent.call = () =>
            Promise.resolve({ operation_status: "success" });

        const result = await this.paymentInterface.send_payment_cancel(order, "C43");

        assert.ok(result);
        assert.strictEqual(payLine.yavin_abort_state, "confirmed");
    });

    QUnit.test("send_payment_cancel surfaces backend abort errors", async function (assert) {
        assert.expect(3);
        const payLine = this.makePayLine({ cid: "C100" });
        const order = this.makeOrder([payLine]);
        const errorMessages = [];
        patchWithCleanup(this.paymentInterface, {
            _show_error: (msg) => {
                errorMessages.push(msg);
            }
        });
        this.env.services.orm.silent.call = () =>
            Promise.resolve({ operation_status: "failure", error_message: "Cannot abort" });
        const result = await this.paymentInterface.send_payment_cancel(order, "C100");
        assert.notOk(result, "abort error keeps the line in a waiting state");
        assert.strictEqual(errorMessages[0], "Cannot abort");
        assert.strictEqual(payLine.yavin_abort_state, null, "abort state reset after abort failure");
    });

    QUnit.test("send_payment_cancel timeout waits for payment response", async function (assert) {
        assert.expect(4);
        const payLine = this.makePayLine({ cid: "CTIMEOUT", yavin_attempt_number: 1 });
        const order = this.makeOrder([payLine]);
        const errorMessages = [];
        patchWithCleanup(this.paymentInterface, {
            _show_error: (msg) => {
                errorMessages.push(msg);
            }
        });
        this.env.services.orm.silent.call = () => Promise.reject(new Error("timeout"));
        const result = await this.paymentInterface.send_payment_cancel(order, "CTIMEOUT");
        assert.notOk(result);
        // On timeout, don't show error, wait for payment response
        assert.strictEqual(errorMessages.length, 0, "no error shown on abort timeout");
        assert.strictEqual(payLine.yavin_abort_state, "requested", "abort state stays pending");
        assert.strictEqual(payLine.yavin_attempt_number, 1, "no increment until abort is confirmed");
    });

    QUnit.test("send_payment_cancel abort failure waits for payment", async function (assert) {
        assert.expect(3);
        const payLine = this.makePayLine({ cid: "CKO" });
        const order = this.makeOrder([payLine]);
        const errorMessages = [];
        patchWithCleanup(this.paymentInterface, {
            _show_error: (msg) => {
                errorMessages.push(msg);
            }
        });
        this.env.services.orm.silent.call = () =>
            Promise.resolve({ operation_status: "failure", error_message: "Cannot abort" });
        const result = await this.paymentInterface.send_payment_cancel(order, "CKO");
        assert.notOk(result);
        assert.strictEqual(errorMessages.length, 1);
        assert.strictEqual(payLine.yavin_abort_state, null, "abort state reset after abort error");
    });

    QUnit.test("send_payment_cancel confirms payment retry if payment arrived first", async function (assert) {
        assert.expect(4);
        const payLine = this.makePayLine({ cid: "CFIRST", yavin_attempt_number: 1 });
        payLine.set_payment_status("retry"); // Payment already set retry
        const order = this.makeOrder([payLine]);
        let handledResponse = null;
        patchWithCleanup(this.paymentInterface, {
            _handle_yavin_response: async (line, response) => {
                handledResponse = { line, response };
                return false;
            }
        });
        this.env.services.orm.silent.call = () =>
            Promise.resolve({ operation_status: "success" });
        const result = await this.paymentInterface.send_payment_cancel(order, "CFIRST");
        assert.ok(result);
        assert.strictEqual(payLine.yavin_abort_state, "confirmed");
        // Should not call _handle_yavin_response if payment already set retry
        assert.strictEqual(handledResponse, null);
        // attempt_number is incremented by send_payment_cancel
        assert.strictEqual(payLine.yavin_attempt_number, 2);
    });

    QUnit.test("send_payment_reversal technical retry keeps same idempotentUuid", async function (assert) {
        assert.expect(3);
        const { payLine } = this.createSendContext({
            payLine: {
                cid: "REV1",
                amount: -5,
                yavin_original_transaction_id: "TX-ORIG",
                yavin_attempt_number: 1,
                yavin_last_reversal_failure_type: "timeout",
            },
        });
        let attemptInPayload;
        this.env.services.orm.silent.call = (...args) => {
            attemptInPayload = args[2][0].attempt_number;
            return Promise.resolve({ operation_status: "success" });
        };

        const result = await this.paymentInterface.send_payment_reversal("REV1", "TX-ORIG");

        assert.ok(result);
        assert.strictEqual(payLine.yavin_attempt_number, 1);
        assert.strictEqual(attemptInPayload, 1);
    });

    QUnit.test("send_payment_reversal retry after failure uses new idempotentUuid", async function (assert) {
        assert.expect(3);
        const { payLine } = this.createSendContext({
            payLine: {
                cid: "REV2",
                amount: -5,
                yavin_original_transaction_id: "TX-ORIG",
                yavin_attempt_number: 1,
                yavin_last_reversal_failure_type: "failure",
            },
        });
        let attemptInPayload;
        this.env.services.orm.silent.call = (...args) => {
            attemptInPayload = args[2][0].attempt_number;
            return Promise.resolve({ operation_status: "success" });
        };

        const result = await this.paymentInterface.send_payment_reversal("REV2", "TX-ORIG");

        assert.ok(result);
        assert.strictEqual(payLine.yavin_attempt_number, 2);
        assert.strictEqual(attemptInPayload, 2);
    });

    QUnit.test("send_payment_reversal failure marks failure type for next retry", async function (assert) {
        assert.expect(2);
        const { payLine } = this.createSendContext({
            payLine: {
                cid: "REV3",
                amount: -5,
                yavin_original_transaction_id: "TX-ORIG",
            },
        });
        patchWithCleanup(this.paymentInterface, {
            _show_error: () => { }
        });
        patchWithCleanup(console, {
            error: () => { },
        });
        this.env.services.orm.silent.call = () =>
            Promise.resolve({ operation_status: "failure", error_message: "Declined" });

        const result = await this.paymentInterface.send_payment_reversal("REV3", "TX-ORIG");

        assert.notOk(result);
        assert.strictEqual(payLine.yavin_last_reversal_failure_type, "failure");
    });

    QUnit.test("send_payment_reversal handles canonical network_error", async function (assert) {
        assert.expect(3);
        const { payLine } = this.createSendContext({
            payLine: {
                cid: "REV-LEGACY-FALLBACK",
                amount: -5,
                yavin_original_transaction_id: "TX-ORIG",
            },
        });
        patchWithCleanup(this.paymentInterface, {
            _show_error: () => { }
        });
        patchWithCleanup(console, {
            error: () => { },
        });
        this.env.services.orm.silent.call = () =>
            Promise.resolve({ operation_status: "network_error", error_message: "Offline" });

        const result = await this.paymentInterface.send_payment_reversal(
            "REV-LEGACY-FALLBACK",
            "TX-ORIG"
        );

        assert.notOk(result);
        assert.strictEqual(payLine.yavin_last_reversal_failure_type, "network_error");
        assert.notOk(payLine.yavin_request_in_progress, "canonical response still releases the line lock");
    });

    QUnit.test("send_payment_reversal validation failure leaves line unlocked", async function (assert) {
        assert.expect(2);
        const { payLine } = this.createSendContext({
            payLine: {
                cid: "REV-LOCK",
                amount: 5,
                payment_status: "retry",
            },
        });
        patchWithCleanup(console, {
            error: () => { },
        });

        const result = await this.paymentInterface.send_payment_reversal("REV-LOCK");

        assert.notOk(result);
        assert.notOk(payLine.yavin_request_in_progress, "validation failure does not leak the line lock");
    });

    QUnit.test("send_payment_reversal abort timeout increments next attempt once on later failure", async function (assert) {
        assert.expect(3);
        const { payLine } = this.createSendContext({
            payLine: {
                cid: "REV4",
                amount: -5,
                yavin_original_transaction_id: "TX-ORIG",
                yavin_attempt_number: 1,
            },
        });
        payLine.yavin_abort_state = "requested";
        patchWithCleanup(this.paymentInterface, {
            _show_error: () => { }
        });
        this.env.services.orm.silent.call = () =>
            Promise.resolve({ operation_status: "failure", error_message: "Aborted" });

        const result = await this.paymentInterface.send_payment_reversal("REV4", "TX-ORIG");

        assert.notOk(result);
        assert.strictEqual(payLine.yavin_attempt_number, 2);
        assert.strictEqual(payLine.yavin_abort_state, null);
    });

    // Since _abort_handled_completely was removed, we might need to skip or update this test
    // this.paymentInterface._abort_handled_completely = true;
    // ...

    QUnit.test("handle_yavin_response payment success before abort treats immediately", async function (assert) {
        assert.expect(4);
        const payLine = this.makePayLine();
        payLine.yavin_abort_state = "requested";
        const result = await this.paymentInterface._handle_yavin_response(payLine, {
            operation_status: "success",
            transaction_id: "TX-1",
        });
        assert.ok(result);
        assert.strictEqual(payLine.payment_status, "done");
        assert.strictEqual(payLine.yavin_abort_state, null, "abort state reset");
        assert.strictEqual(payLine.transaction_id, "TX-1");
    });

    QUnit.test("handle_yavin_response payment failure before abort increments next attempt once", async function (assert) {
        assert.expect(5);
        const payLine = this.makePayLine({ yavin_attempt_number: 1 });
        payLine.yavin_abort_state = "requested";
        const errorCalls = [];
        patchWithCleanup(this.paymentInterface, {
            _handle_error: (msg) => {
                errorCalls.push(msg);
                return false;
            }
        });
        const result = await this.paymentInterface._handle_yavin_response(payLine, {
            operation_status: "failure",
            error_message: "Declined",
        });
        assert.notOk(result);
        assert.strictEqual(payLine.payment_status, "retry");
        assert.strictEqual(payLine.yavin_abort_state, null, "abort state reset after failure handled");
        assert.strictEqual(errorCalls.length, 0, "no error shown, abort was expected");
        assert.strictEqual(payLine.yavin_attempt_number, 2, "next payment uses a new idempotentUuid");
    });

    QUnit.test("handle_yavin_response payment failure after abort timeout treats as failure", async function (assert) {
        assert.expect(4);
        const payLine = this.makePayLine({ yavin_attempt_number: 1 });
        payLine.yavin_abort_state = "requested"; // Abort timeout, waiting for payment
        const errorCalls = [];
        patchWithCleanup(this.paymentInterface, {
            _handle_error: (msg) => {
                errorCalls.push(msg);
                return false;
            }
        });
        const result = await this.paymentInterface._handle_yavin_response(payLine, {
            operation_status: "failure",
            error_message: "Declined",
        });
        assert.notOk(result);
        assert.strictEqual(payLine.payment_status, "retry");
        // When abort_expected_failure is true, failure is treated as expected (no error shown)
        assert.strictEqual(errorCalls.length, 0, "no error shown (abort was expected)");
        assert.strictEqual(payLine.yavin_attempt_number, 2, "next payment uses a new idempotentUuid");
    });

    QUnit.test("check_pending_transactions silently recovers recent payment lines", async function (assert) {
        assert.expect(1);
        const now = Date.now();
        const payLine = this.makePayLine({
            cid: "RECOVER-PAY",
            payment_status: "waitingCard",
            yavin_attempt_number: 1,
            yavin_payment_request_time: now,
            yavin_operation_type: "payment",
        });
        const order = this.makeOrder([payLine], { selected_paymentline: payLine });
        let recoveredCid = null;
        patchWithCleanup(this.paymentInterface, {
            send_payment_request: async (cid) => {
                recoveredCid = cid;
                return true;
            }
        });

        this.paymentInterface.check_pending_transactions(order);

        assert.strictEqual(recoveredCid, "RECOVER-PAY");
    });

    QUnit.test("check_pending_transactions silently recovers recent reversal lines", async function (assert) {
        assert.expect(1);
        const now = Date.now();
        const payLine = this.makePayLine({
            cid: "RECOVER-REV",
            payment_status: "waitingCard",
            yavin_attempt_number: 1,
            yavin_payment_request_time: now,
            yavin_operation_type: YAVIN_OPERATION_REVERSAL,
            transaction_id: "TX-REV",
        });
        const order = this.makeOrder([payLine], { selected_paymentline: payLine });
        let recoveredCid = null;
        patchWithCleanup(this.paymentInterface, {
            send_payment_reversal: async (cid) => {
                recoveredCid = cid;
                return true;
            }
        });

        this.paymentInterface.check_pending_transactions(order);

        assert.strictEqual(recoveredCid, "RECOVER-REV");
    });

    QUnit.test("check_pending_transactions resets stale payment lines to retry", function (assert) {
        assert.expect(1);
        const payLine = this.makePayLine({
            payment_status: "waitingCard",
            yavin_attempt_number: 1,
            yavin_payment_request_time: Date.now() - 200000,
            yavin_operation_type: "payment",
        });
        const order = this.makeOrder([payLine], { selected_paymentline: payLine });

        this.paymentInterface.check_pending_transactions(order);

        assert.strictEqual(payLine.payment_status, "retry");
    });

    QUnit.test("check_pending_transactions resets stale positive reversal lines to done", function (assert) {
        assert.expect(2);
        const payLine = this.makePayLine({
            payment_status: "waitingCard",
            yavin_attempt_number: 1,
            yavin_payment_request_time: Date.now() - 200000,
            yavin_operation_type: YAVIN_OPERATION_REVERSAL,
            amount: 5,
        });
        const order = this.makeOrder([payLine], { selected_paymentline: payLine });

        this.paymentInterface.check_pending_transactions(order);

        assert.strictEqual(payLine.payment_status, "done");
        assert.ok(payLine.can_be_reversed, "positive reversal stays reversible after stale recovery");
    });
});

QUnit.module("pos_yavin lifecycle utilities", () => {
    QUnit.test("shouldRecoverYavinLine only recovers recent terminal lines", function (assert) {
        assert.expect(2);
        const recentLine = {
            payment_method: { use_payment_terminal: "yavin", yavin_timeout_ms: 1000 },
            yavin_attempt_number: 1,
            yavin_payment_request_time: Date.now(),
            get_payment_status: () => "waitingCard",
        };
        const staleLine = {
            payment_method: { use_payment_terminal: "yavin", yavin_timeout_ms: 1000 },
            yavin_attempt_number: 1,
            yavin_payment_request_time: Date.now() - 5000,
            get_payment_status: () => "waitingCard",
        };

        assert.ok(shouldRecoverYavinLine(recentLine));
        assert.notOk(shouldRecoverYavinLine(staleLine));
    });

    QUnit.test("getYavinStaleStatus keeps positive reversals on done", function (assert) {
        assert.expect(2);
        assert.strictEqual(
            getYavinStaleStatus({ yavin_operation_type: YAVIN_OPERATION_REVERSAL, amount: 10 }),
            "done"
        );
        assert.strictEqual(
            getYavinStaleStatus({ yavin_operation_type: YAVIN_OPERATION_REVERSAL, amount: -10 }),
            "retry"
        );
    });
});

QUnit.module("pos_yavin tip visibility helpers", () => {
    QUnit.test("shouldDisplayYavinTip only hides tips for Yavin orders with hidden tip display", function (assert) {
        assert.expect(3);
        const pos = {
            config: { iface_tipproduct: true },
        };
        const orderWithoutYavin = {
            paymentlines: [],
        };
        const orderWithVisibleTip = {
            paymentlines: [{ payment_method: { use_payment_terminal: "yavin", yavin_display_tip: true } }],
        };
        const orderWithHiddenTip = {
            paymentlines: [{ payment_method: { use_payment_terminal: "yavin", yavin_display_tip: false } }],
        };

        assert.ok(shouldDisplayYavinTip(orderWithoutYavin, pos));
        assert.ok(shouldDisplayYavinTip(orderWithVisibleTip, pos));
        assert.notOk(shouldDisplayYavinTip(orderWithHiddenTip, pos));
    });

    QUnit.test("filterYavinTipLines leaves unrelated orders untouched", function (assert) {
        assert.expect(2);
        const pos = {
            config: { iface_tipproduct: true },
            db: {
                get_product_by_id: () => ({ id: 42 }),
                search_product: () => [{ id: 42, default_code: "TIPS" }],
            },
        };
        const lines = [
            { product: { id: 1 } },
            { product: { id: 42 } },
        ];
        const unrelatedOrder = { paymentlines: [] };
        const hiddenTipOrder = {
            paymentlines: [{ payment_method: { use_payment_terminal: "yavin", yavin_display_tip: false } }],
        };

        assert.deepEqual(filterYavinTipLines(unrelatedOrder, pos, lines), lines);
        assert.deepEqual(filterYavinTipLines(hiddenTipOrder, pos, lines), [{ product: { id: 1 } }]);
    });
});

QUnit.module("pos_yavin PaymentScreen override", () => {
    QUnit.test("sendPaymentReverse keeps Yavin reversal retryable on failure", async function (assert) {
        assert.expect(3);
        const line = {
            amount: 5,
            can_be_reversed: true,
            payment_method: {
                use_payment_terminal: "yavin",
                payment_terminal: {
                    send_payment_reversal: async () => false,
                },
            },
            set_payment_status(status) {
                this.payment_status = status;
            },
            set_amount(amount) {
                this.amount = amount;
            },
        };

        await PaymentScreen.prototype.sendPaymentReverse.call({}, line);

        assert.strictEqual(line.payment_status, "done");
        assert.ok(line.can_be_reversed, "reverse button remains available");
        assert.strictEqual(line.amount, 5, "original amount is preserved");
    });
});

QUnit.module("pos_yavin YavinTipHandler", (hooks) => {
    hooks.beforeEach(function () {
        this.rpcCalls = [];
        this.env = {
            services: {
                orm: {
                    silent: {
                        call: (...args) => {
                            this.rpcCalls.push(args);
                            return Promise.resolve();
                        },
                    },
                },
            },
        };
        this.pos = {
            config: { iface_tipproduct: true },
            db: {
                get_product_by_id: () => null,
                search_product: () => [],
            },
            _addProducts: () => Promise.resolve(),
            validated_orders_name_server_id_map: {},
        };
        this.payLine = { amount: 5 };
    });

    QUnit.test("getTipProduct searches server tip product with a valid Odoo domain", async function (assert) {
        assert.expect(5);
        const tipProduct = { id: 42, default_code: "TIPS" };
        const addedProductIds = [];
        this.pos._addProducts = async (productIds) => {
            addedProductIds.push(productIds);
        };
        this.pos.db.get_product_by_id = (id) => (id === 42 ? tipProduct : null);
        this.env.services.orm.silent.call = (...args) => {
            this.rpcCalls.push(args);
            return Promise.resolve([42]);
        };

        const result = await YavinTipHandler.getTipProduct(this.pos, this.env);

        assert.strictEqual(result, tipProduct);
        assert.strictEqual(this.rpcCalls.length, 1);
        assert.deepEqual(this.rpcCalls[0].slice(0, 3), [
            "product.product",
            "search",
            [[["default_code", "=", "TIPS"]]],
        ]);
        assert.deepEqual(this.rpcCalls[0][3], { limit: 1 });
        assert.deepEqual(addedProductIds, [[42]]);
    });

    QUnit.test("handleTipFromResponse adds visible tip line", async function (assert) {
        assert.expect(4);
        const order = {
            finalized: false,
            set_tip(amount) {
                this.tip_amount = amount;
            },
        };
        let updatedAmount = null;
        this.payLine.set_amount = (amount) => {
            updatedAmount = amount;
            this.payLine.amount = amount;
        };
        patchWithCleanup(YavinTipHandler, {
            getTipProduct: () => ({ id: 42 })
        });
        await YavinTipHandler.handleTipFromResponse({
            order,
            pay_line: this.payLine,
            gift_amount: 3,
            pos: this.pos,
            env: this.env,
            yavinPaymentMethod: { yavin_display_tip: true },
        });
        assert.strictEqual(order.tip_amount, 3);
        assert.strictEqual(this.payLine.amount, 8);
        assert.strictEqual(updatedAmount, 8, "payment line amount is updated through the model API");
        assert.strictEqual(this.rpcCalls.length, 0);
    });

    QUnit.test("handleTipFromResponse stores hidden tip when display disabled", async function (assert) {
        assert.expect(4);
        const order = { tip_amount: 0, is_tipped: false, name: "ORD1" };
        this.pos.validated_orders_name_server_id_map = { ORD1: 99 };
        const rpcSpy = [];
        this.env.services.orm.silent.call = (...args) => {
            rpcSpy.push(args);
            return Promise.resolve();
        };
        await YavinTipHandler.handleTipFromResponse({
            order,
            pay_line: this.payLine,
            gift_amount: 4,
            pos: this.pos,
            env: this.env,
            yavinPaymentMethod: { yavin_display_tip: false },
        });
        assert.strictEqual(this.payLine.amount, 5, "amount unchanged");
        assert.strictEqual(order.tip_amount, 4);
        assert.ok(order.is_tipped);
        assert.deepEqual(rpcSpy[0], [
            "pos.order",
            "write",
            [[99], { tip_amount: 4, is_tipped: true }],
        ]);
    });
});

