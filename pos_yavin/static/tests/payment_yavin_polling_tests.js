/** @odoo-module **/

import { PaymentYavin } from "@pos_yavin/payment/payment_yavin";

QUnit.module("pos_yavin CloudPolling", (hooks) => {
    hooks.beforeEach(function () {
        this.rpcCalls = [];
        this.statusCallCount = 0;
        this.env = {
            services: {
                popup: {
                    add: () => {},
                },
                orm: {
                    silent: {
                        call: (model, method, args) => {
                            this.rpcCalls.push({ model, method, args });
                            if (method === "yavin_cloud_start") {
                                return Promise.resolve({
                                    operation_status: "pending",
                                    yavin_tx_id: 99,
                                });
                            }
                            if (method === "yavin_cloud_status") {
                                this.statusCallCount += 1;
                                const payload = args[0] || {};
                                if (payload.expire) {
                                    return Promise.resolve({
                                        operation_status: "timeout",
                                        error_message: "No webhook",
                                        retryable: true,
                                    });
                                }
                                if (this.statusCallCount < 3) {
                                    return Promise.resolve({ operation_status: "pending" });
                                }
                                return Promise.resolve({
                                    operation_status: "success",
                                    transaction_id: "TX-OK",
                                    card_type: "VISA",
                                    yavin_issuer: "Bank",
                                    ticket: "",
                                });
                            }
                            return Promise.resolve({});
                        },
                    },
                },
            },
            utils: {},
        };
        this.paymentMethod = {
            id: 7,
            use_payment_terminal: "yavin",
            yavin_effective_connection_mode: "cloud",
            yavin_timeout_ms: 5000,
            yavin_display_tip: false,
            payment_terminal: { supports_reversals: true },
        };
        this.payLine = {
            cid: "PL1",
            amount: 10,
            yavin_attempt_number: 1,
            payment_status: "",
            statuses: [],
            order: null,
            payment_method: this.paymentMethod,
            set_payment_status(status) {
                this.payment_status = status;
                this.statuses.push(status);
            },
            get_payment_status() {
                return this.payment_status;
            },
            set_receipt_info() {},
        };
        this.order = {
            uid: "OU1",
            pos_session_id: 1,
            partner: null,
            selected_paymentline: this.payLine,
            get_paymentline(cid) {
                return cid === "PL1" ? this.selected_paymentline : null;
            },
        };
        this.payLine.order = this.order;
        this.pos = {
            env: this.env,
            currency: { id: 1 },
            config: {},
            get_cashier: () => ({ name: "Test" }),
            get_order: () => this.order,
        };
        this.terminal = new PaymentYavin(this.pos, this.paymentMethod);
    });

    QUnit.test("cloud polling calls start then status with payment_method_id", async function (assert) {
        const done = assert.async();
        const r = await this.terminal.send_payment_request("PL1");
        assert.ok(r);
        assert.strictEqual(this.payLine.transaction_id, "TX-OK");
        const statusCalls = this.rpcCalls.filter((c) => c.method === "yavin_cloud_status");
        assert.ok(statusCalls.length >= 3, "at least 3 status polls before success");
        statusCalls.forEach((c) => {
            const p = c.args[0];
            assert.strictEqual(p.payment_method_id, 7, "status must include payment_method_id");
            assert.strictEqual(p.yavin_tx_id, 99);
        });
        done();
    });

    QUnit.test("cloud start failure skips polling", async function (assert) {
        const done = assert.async();
        this.env.services.orm.silent.call = (model, method, args) => {
            this.rpcCalls.push({ model, method, args });
            if (method === "yavin_cloud_start") {
                return Promise.resolve({
                    operation_status: "failure",
                    error_message: "Declined",
                });
            }
            return Promise.reject(new Error("should not poll"));
        };
        const terminal = new PaymentYavin(this.pos, this.paymentMethod);
        const r = await terminal.send_payment_request("PL1");
        assert.strictEqual(r, false);
        assert.ok(
            this.rpcCalls.every((c) => c.method !== "yavin_cloud_status"),
            "no status when start fails"
        );
        done();
    });

    QUnit.test("cloud status errors retry then succeed", async function (assert) {
        const done = assert.async();
        let n = 0;
        this.env.services.orm.silent.call = (model, method, args) => {
            this.rpcCalls.push({ model, method, args });
            if (method === "yavin_cloud_start") {
                return Promise.resolve({
                    operation_status: "pending",
                    yavin_tx_id: 50,
                });
            }
            if (method === "yavin_cloud_status") {
                n += 1;
                if (n === 1) {
                    return Promise.reject(new Error("network"));
                }
                if (args[0].expire) {
                    return Promise.resolve({
                        operation_status: "timeout",
                        error_message: "t",
                        retryable: true,
                    });
                }
                return Promise.resolve({
                    operation_status: "success",
                    transaction_id: "R1",
                    card_type: "MC",
                    yavin_issuer: "",
                    ticket: "",
                });
            }
            return Promise.resolve({});
        };
        const terminal = new PaymentYavin(this.pos, this.paymentMethod);
        const r = await terminal.send_payment_request("PL1");
        assert.ok(r);
        assert.strictEqual(this.payLine.transaction_id, "R1");
        done();
    });

    QUnit.test("abort requested during cloud polling stops status loop", async function (assert) {
        const done = assert.async();
        let pollCount = 0;
        this.env.services.orm.silent.call = async (model, method, args) => {
            this.rpcCalls.push({ model, method, args });
            if (method === "yavin_cloud_start") {
                return {
                    operation_status: "pending",
                    yavin_tx_id: 77,
                };
            }
            if (method === "yavin_cloud_status") {
                pollCount += 1;
                if (pollCount === 1) {
                    this.payLine.yavin_abort_state = "requested";
                }
                return { operation_status: "pending" };
            }
            return {};
        };

        const terminal = new PaymentYavin(this.pos, this.paymentMethod);
        const result = await terminal.send_payment_request("PL1", { silentError: true });

        assert.strictEqual(result, false, "request stops cleanly when abort is pending");
        assert.strictEqual(
            this.payLine.get_payment_status(),
            "waitingCard",
            "status is preserved while abort is still pending"
        );
        assert.strictEqual(
            this.payLine.yavin_abort_state,
            "requested",
            "abort marker remains set for subsequent abort flow"
        );
        assert.strictEqual(
            this.payLine.yavin_request_in_progress,
            false,
            "in-progress flag is always cleared in finally block"
        );
        const statusCalls = this.rpcCalls.filter((c) => c.method === "yavin_cloud_status");
        assert.strictEqual(statusCalls.length, 1, "polling loop exits immediately after abort signal");
        done();
    });

    QUnit.test("check_pending_transactions recovers recent retry line after reload", function (assert) {
        const done = assert.async();
        const terminal = new PaymentYavin(this.pos, this.paymentMethod);
        let recovered = 0;
        terminal.send_payment_request = async (cid, options = {}) => {
            recovered += 1;
            assert.strictEqual(cid, "PL1");
            assert.ok(Boolean(options.silentError), "reload recovery uses silent mode");
            return true;
        };

        this.payLine.yavin_attempt_number = 3;
        this.payLine.yavin_payment_request_time = Date.now();
        this.payLine.set_payment_status("retry");
        this.order.get_paymentlines = () => [this.payLine];

        terminal.check_pending_transactions(this.order);

        setTimeout(() => {
            assert.strictEqual(recovered, 1, "recent recoverable line is replayed once");
            done();
        }, 0);
    });
});
