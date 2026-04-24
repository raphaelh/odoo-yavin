/** @odoo-module **/

import {
    getOrderYavinPaymentMethod,
    getPosRefundLinesTotalWithTax,
    getTipProductId,
} from "@pos_yavin/overrides/models/models";
import { Order, Payment } from "@point_of_sale/app/store/models";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patchWithCleanup } from "@web/../tests/helpers/utils";

const { DateTime } = luxon;

QUnit.module("pos_yavin models helpers", () => {
    QUnit.test("getTipProductId prefers configured tip product", function (assert) {
        const pos = {
            config: { tip_product_id: [42, "Tips"] },
            db: {
                get_product_by_id: (id) => (id === 42 ? { id: 42 } : null),
                search_product: () => [{ id: 99, default_code: "TIPS" }],
            },
        };

        assert.strictEqual(getTipProductId(pos), 42);
    });

    QUnit.test("getTipProductId falls back to exact TIPS product code", function (assert) {
        const pos = {
            config: {},
            db: {
                get_product_by_id: () => null,
                search_product: () => [
                    { id: 1, default_code: "TIP" },
                    { id: 2, default_code: "TIPS" },
                ],
            },
        };

        assert.strictEqual(getTipProductId(pos), 2);
    });

    QUnit.test("getOrderYavinPaymentMethod returns first Yavin payment method", function (assert) {
        const yavinMethod = { use_payment_terminal: "yavin" };
        const order = {
            paymentlines: [
                { payment_method: { use_payment_terminal: "none" } },
                { payment_method: yavinMethod },
            ],
        };

        assert.strictEqual(getOrderYavinPaymentMethod(order), yavinMethod);
        assert.strictEqual(getOrderYavinPaymentMethod({ paymentlines: [] }), null);
    });

    QUnit.test("getPosRefundLinesTotalWithTax sums only refunded_orderline_id lines", function (assert) {
        const order = {
            get_orderlines: () => [
                { refunded_orderline_id: 1, get_price_with_tax: () => 2.38 },
                { refunded_orderline_id: null, get_price_with_tax: () => 0.11 },
                { refunded_orderline_id: false, get_price_with_tax: () => 5 },
            ],
        };
        assert.strictEqual(getPosRefundLinesTotalWithTax(order), 2.38);
        assert.strictEqual(getPosRefundLinesTotalWithTax(null), 0);
    });
});

QUnit.module("pos_yavin models patches", () => {
    QUnit.test("Order export_for_printing includes Yavin tip metadata", function (assert) {
        const fakeOrder = {
            paymentlines: [
                {
                    is_change: false,
                    payment_method: { use_payment_terminal: "yavin", yavin_display_tip: false },
                    export_for_printing: () => ({ amount: 10, name: "Card" }),
                },
            ],
            orderlines: [
                {
                    getDisplayData: () => ({ product_name: "Product", internalNote: "hidden" }),
                },
                {
                    getDisplayData: () => ({ product_name: "Tip", product: { id: 42 } }),
                },
            ],
            pos: {
                base_url: "http://localhost:8069",
                is_french_country: () => false,
                company: {
                    point_of_sale_use_ticket_qr_code: false,
                    point_of_sale_ticket_unique_code: false,
                },
                getReceiptHeaderData: () => ({}),
                config: {
                    receipt_footer: "Footer",
                    iface_tipproduct: true,
                    tip_product_id: [42, "Tips"],
                },
                db: {
                    get_product_by_id: (id) => (id === 42 ? { id: 42 } : null),
                    search_product: () => [{ id: 42, default_code: "TIPS" }],
                },
            },
            tip_amount: 3,
            locked: false,
            finalized: false,
            state: "draft",
            date_order: DateTime.local(2024, 1, 1, 10, 0, 0),
            get_total_with_tax: () => 13,
            get_total_without_tax: () => 10,
            get_total_tax: () => 3,
            get_total_paid: () => 13,
            get_total_discount: () => 0,
            get_rounding_applied: () => false,
            get_tax_details: () => ({}),
            get_change: () => 0,
            get_name: () => "ORDER-1",
            get_l10n_fr_hash: () => "",
        };

        const result = Order.prototype.export_for_printing.call(fakeOrder);

        assert.strictEqual(result.tip_amount, 3);
        assert.strictEqual(result.yavin_display_tip, false);
        assert.deepEqual(result.orderlines, [{ product_name: "Product" }]);
    });

    QUnit.test("Payment init_from_JSON restores Yavin fields", function (assert) {
        const paymentMethod = { id: 5, name: "Yavin", use_payment_terminal: "yavin" };
        const fakePayment = {
            pos: { payment_methods_by_id: { 5: paymentMethod } },
        };

        Payment.prototype.init_from_JSON.call(fakePayment, {
            amount: 10,
            payment_method_id: 5,
            can_be_reversed: true,
            payment_status: "waitingCard",
            ticket: "ticket",
            card_type: "CB",
            cardholder_name: "John",
            transaction_id: "TX-1",
            is_change: false,
            yavin_issuer: "Swile",
            yavin_attempt_number: 2,
            yavin_payment_request_time: 123,
            yavin_original_transaction_id: "TX-ORIG",
            yavin_last_failure_type: "failure",
            yavin_last_reversal_failure_type: "timeout",
            yavin_abort_state: "requested",
            yavin_operation_type: "reversal",
        });

        assert.strictEqual(fakePayment.payment_method, paymentMethod);
        assert.strictEqual(fakePayment.yavin_issuer, "Swile");
        assert.strictEqual(fakePayment.yavin_attempt_number, 2);
        assert.strictEqual(fakePayment.yavin_original_transaction_id, "TX-ORIG");
        assert.strictEqual(fakePayment.yavin_operation_type, "reversal");
    });

    QUnit.test("Payment export_as_JSON persists Yavin fields", function (assert) {
        const fakePayment = {
            payment_method: { id: 5, use_payment_terminal: "yavin" },
            get_amount: () => 12,
            payment_status: "retry",
            can_be_reversed: true,
            ticket: "ticket",
            card_type: "VISA",
            cardholder_name: "John",
            transaction_id: "TX-2",
            yavin_issuer: "Edenred",
            yavin_attempt_number: 3,
            yavin_payment_request_time: 456,
            yavin_original_transaction_id: "TX-ORIG",
            yavin_last_failure_type: "timeout",
            yavin_last_reversal_failure_type: "failure",
            yavin_abort_state: "confirmed",
            yavin_operation_type: "payment",
        };

        const result = Payment.prototype.export_as_JSON.call(fakePayment);

        assert.strictEqual(result.payment_method_id, 5);
        assert.strictEqual(result.yavin_issuer, "Edenred");
        assert.strictEqual(result.yavin_attempt_number, 3);
        assert.strictEqual(result.yavin_abort_state, "confirmed");
        assert.strictEqual(result.yavin_operation_type, "payment");
    });

    QUnit.test("Payment handle_payment_response preserves Yavin-managed statuses", function (assert) {
        const fakePayment = {
            payment_method: {
                use_payment_terminal: "yavin",
                payment_terminal: { supports_reversals: true },
            },
            yavin_preserve_status: true,
        };

        const result = Payment.prototype.handle_payment_response.call(fakePayment, true);

        assert.ok(result);
        assert.notOk("yavin_preserve_status" in fakePayment);
        assert.ok(fakePayment.can_be_reversed);
    });

    QUnit.test("PosStore _clearStaleYavinPaymentStatuses resets stale payment lines", function (assert) {
        const fixedNow = 200000;
        const line = {
            payment_method: { use_payment_terminal: "yavin", yavin_timeout_ms: 1000 },
            yavin_request_in_progress: false,
            yavin_abort_state: "requested",
            yavin_payment_request_time: 0,
            yavin_operation_type: "payment",
            get_payment_status: () => "waitingCard",
            set_payment_status(status) {
                this.payment_status = status;
            },
        };
        const store = {
            get_order_list: () => [
                {
                    get_paymentlines: () => [line],
                },
            ],
        };

        patchWithCleanup(Date, { now: () => fixedNow });
        PosStore.prototype._clearStaleYavinPaymentStatuses.call(store);

        assert.strictEqual(line.payment_status, "retry");
        assert.strictEqual(line.yavin_abort_state, null);
        assert.strictEqual(line.yavin_request_in_progress, false);
    });

    QUnit.test("PosStore _clearStaleYavinPaymentStatuses keeps positive reversals done", function (assert) {
        const fixedNow = 200000;
        const line = {
            payment_method: { use_payment_terminal: "yavin", yavin_reversal_timeout_ms: 1000 },
            yavin_request_in_progress: false,
            yavin_abort_state: "requested",
            yavin_payment_request_time: 1,
            yavin_operation_type: "reversal",
            amount: 5,
            get_payment_status: () => "waitingCard",
            set_payment_status(status) {
                this.payment_status = status;
            },
        };
        const store = {
            get_order_list: () => [
                {
                    get_paymentlines: () => [line],
                },
            ],
        };

        patchWithCleanup(Date, { now: () => fixedNow });
        PosStore.prototype._clearStaleYavinPaymentStatuses.call(store);

        assert.strictEqual(line.payment_status, "done");
        assert.strictEqual(line.can_be_reversed, true);
        assert.strictEqual(line.yavin_operation_type, null);
    });

    QUnit.test("PosStore _clearStaleYavinPaymentStatuses keeps active requests untouched", function (assert) {
        const fixedNow = 200000;
        const line = {
            payment_method: { use_payment_terminal: "yavin", yavin_timeout_ms: 1000 },
            yavin_request_in_progress: true,
            yavin_abort_state: "requested",
            yavin_payment_request_time: fixedNow,
            get_payment_status: () => "waitingCard",
            set_payment_status() {
                assert.step("should-not-reset");
            },
        };
        const store = {
            get_order_list: () => [
                {
                    get_paymentlines: () => [line],
                },
            ],
        };

        patchWithCleanup(Date, { now: () => fixedNow });
        PosStore.prototype._clearStaleYavinPaymentStatuses.call(store);

        assert.verifySteps([]);
        assert.strictEqual(line.yavin_abort_state, "requested");
        assert.strictEqual(line.yavin_request_in_progress, true);
    });
});
