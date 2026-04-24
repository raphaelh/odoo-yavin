# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for Yavin Cloud start + status polling RPC flow."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,protected-access

from unittest.mock import patch

import requests

from odoo.tests.common import TransactionCase

from odoo.addons.pos_yavin.models.yavin.constants import YAVIN_TIMEOUT_ERROR_MSG


class TestCloudPolling(TransactionCase):
    """Cloud payment short-RPC flow (start + status + webhook recovery)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        eur = cls.env.ref("base.EUR")
        cls.company = cls.env["res.company"].create(
            {
                "name": "Yavin Cloud Polling Co",
                "currency_id": eur.id,
            }
        )
        cls.env.user.company_ids |= cls.company
        cls.env.user.company_id = cls.company
        cls.bank_journal = cls.env["account.journal"].search(
            [
                ("company_id", "=", cls.company.id),
                ("type", "=", "bank"),
            ],
            limit=1,
        )
        if not cls.bank_journal:
            cls.bank_journal = cls.env["account.journal"].create(
                {
                    "name": "Yavin Polling Bank",
                    "code": "YCPB",
                    "type": "bank",
                    "company_id": cls.company.id,
                    "currency_id": eur.id,
                }
            )

    def setUp(self):
        super().setUp()
        # Production flow uses intentional commits; disable them in TransactionCase
        # to keep per-test savepoints valid.
        self._commit_patcher = patch.object(
            type(self.env.cr), "commit", autospec=True, return_value=None
        )
        self._commit_patcher.start()

    def tearDown(self):
        self._commit_patcher.stop()
        super().tearDown()

    def _create_cloud_method(self, name="Cloud Method"):
        return self.env["pos.payment.method"].create(
            {
                "name": name,
                "company_id": self.company.id,
                "journal_id": self.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "cloud",
                "yavin_terminal_serial": "SERIAL1",
                "yavin_cloud_api_key": "secret-key",
            }
        )

    def _base_payload(self, method, **kw):
        data = {
            "payment_method_id": method.id,
            "amount": 10.0,
            "currency_id": self.company.currency_id.id,
            "payment_id": "P1",
            "order_uid": "O1",
            "timeout": 60000,
            "attempt_number": 1,
            "cashier_name": "Test",
            "session_id": None,
            "partner_id": None,
        }
        data.update(kw)
        return data

    def test_cloud_start_creates_pending_tx_and_commits(self):
        method = self._create_cloud_method()
        payload = self._base_payload(method)
        with patch(
            "odoo.addons.pos_yavin.models.yavin.application.cloud_payment.YavinCloudClient.start_payment",
            return_value={"status": "ok", "transactionId": "TID42"},
        ):
            result = self.env["pos.payment.method"].yavin_cloud_start(payload)
        self.assertEqual(result["operation_status"], "pending")
        self.assertIsInstance(result["yavin_tx_id"], int)
        tx = self.env["yavin.cloud.transaction"].browse(result["yavin_tx_id"])
        self.assertTrue(tx.exists())
        self.assertEqual(tx.state, "pending")
        self.assertEqual(tx.cloud_transaction_id, "TID42")
        self.assertEqual(tx.idempotent_uuid, "O1-P1-1")

    def test_cloud_start_http_failure_marks_error_and_returns_timeout(self):
        method = self._create_cloud_method()
        payload = self._base_payload(method)
        with patch(
            "odoo.addons.pos_yavin.models.yavin.application.cloud_payment.YavinCloudClient.start_payment",
            side_effect=requests.exceptions.Timeout,
        ):
            result = self.env["pos.payment.method"].yavin_cloud_start(payload)
        self.assertEqual(result["operation_status"], "timeout")
        tx = self.env["yavin.cloud.transaction"].search(
            [("payment_method_id", "=", method.id)], limit=1
        )
        self.assertEqual(tx.state, "error")

    def test_cloud_start_status_ko_returns_failure(self):
        method = self._create_cloud_method()
        payload = self._base_payload(method)
        with patch(
            "odoo.addons.pos_yavin.models.yavin.application.cloud_payment.YavinCloudClient.start_payment",
            return_value={"status": "ko", "message": "Refused"},
        ):
            result = self.env["pos.payment.method"].yavin_cloud_start(payload)
        self.assertEqual(result["operation_status"], "failure")
        self.assertIn("Refused", result["error_message"])

    def test_cloud_start_missing_tid_returns_issue(self):
        method = self._create_cloud_method()
        payload = self._base_payload(method)
        with patch(
            "odoo.addons.pos_yavin.models.yavin.application.cloud_payment.YavinCloudClient.start_payment",
            return_value={"status": "ok"},
        ):
            result = self.env["pos.payment.method"].yavin_cloud_start(payload)
        self.assertEqual(result["operation_status"], "issue")

    def test_cloud_status_pending_returns_pending(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u1",
                "cart_id": "c1",
                "currency_id": self.company.currency_id.id,
                "cloud_transaction_id": "T1",
            }
        )
        result = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": tx.id, "payment_method_id": method.id, "expire": False}
        )
        self.assertEqual(result["operation_status"], "pending")
        self.assertEqual(result["yavin_tx_id"], tx.id)

    def test_cloud_status_done_returns_parsed_payload(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u2",
                "cart_id": "c2",
                "currency_id": self.company.currency_id.id,
                "cloud_transaction_id": "T2",
                "state": "done",
                "result_payload": {
                    "status": "ok",
                    "trs_id": "T2",
                    "scheme": "VISA",
                    "issuer": "Bank",
                    "client_ticket": "TICK",
                    "gift_amount": 0,
                },
            }
        )
        result = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": tx.id, "payment_method_id": method.id, "expire": False}
        )
        self.assertEqual(result["operation_status"], "success")
        self.assertEqual(result["transaction_id"], "T2")
        self.assertEqual(result["card_type"], "VISA")

    def test_cloud_status_error_returns_failure_with_message(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u3",
                "cart_id": "c3",
                "currency_id": self.company.currency_id.id,
                "state": "error",
                "error_message": "Declined",
            }
        )
        result = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": tx.id, "payment_method_id": method.id, "expire": False}
        )
        self.assertEqual(result["operation_status"], "failure")
        self.assertEqual(result["error_message"], "Declined")

    def test_cloud_status_unknown_tx_returns_issue(self):
        method = self._create_cloud_method()
        result = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": 999999999, "payment_method_id": method.id, "expire": False}
        )
        self.assertEqual(result["operation_status"], "issue")

    def test_cloud_status_expire_marks_error_and_returns_timeout(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u4",
                "cart_id": "c4",
                "currency_id": self.company.currency_id.id,
                "cloud_transaction_id": "T4",
            }
        )
        result = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": tx.id, "payment_method_id": method.id, "expire": True}
        )
        self.assertEqual(result["operation_status"], "timeout")
        tx.invalidate_recordset()
        self.assertEqual(tx.state, "error")
        self.assertEqual(tx.error_message, YAVIN_TIMEOUT_ERROR_MSG)

    def test_cloud_status_expire_skips_when_already_done(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u5",
                "cart_id": "c5",
                "currency_id": self.company.currency_id.id,
                "cloud_transaction_id": "T5",
                "state": "done",
                "result_payload": {
                    "status": "ok",
                    "trs_id": "T5",
                    "scheme": "MC",
                    "issuer": "X",
                    "client_ticket": "",
                    "gift_amount": 0,
                },
            }
        )
        result = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": tx.id, "payment_method_id": method.id, "expire": True}
        )
        self.assertEqual(result["operation_status"], "success")

    def test_webhook_then_status_chain(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u6",
                "cart_id": "ORDER6",
                "currency_id": self.company.currency_id.id,
                "cloud_transaction_id": "T6",
            }
        )
        self.env["yavin.cloud.transaction"]._yavin_process_webhook(
            method.yavin_webhook_token,
            {
                "status": "ok",
                "trs_id": "T6",
                "cartId": "ORDER6",
                "scheme": "VISA",
                "issuer": "I",
                "client_ticket": "Z",
                "gift_amount": 0,
            },
        )
        result = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": tx.id, "payment_method_id": method.id, "expire": False}
        )
        self.assertEqual(result["operation_status"], "success")

    def test_yavin_send_payment_compat_delegates_to_start_cloud(self):
        method = self._create_cloud_method()
        payload = self._base_payload(method)
        with patch(
            "odoo.addons.pos_yavin.models.yavin.application.cloud_payment.YavinCloudClient.start_payment",
            return_value={"status": "ok", "transactionId": "T7"},
        ):
            result = self.env["pos.payment.method"].yavin_send_payment(payload)
        self.assertEqual(result["operation_status"], "pending")
        self.assertIn("yavin_tx_id", result)

    def test_local_api_unchanged_send_payment_uses_client(self):
        from odoo.addons.pos_yavin.models.yavin.validation import YavinPaymentValidator

        method = self.env["pos.payment.method"].create(
            {
                "name": "Local Yavin",
                "company_id": self.company.id,
                "journal_id": self.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "local",
                "yavin_ip_address": "127.0.0.1",
            }
        )
        payload = {
            "payment_method_id": method.id,
            "amount": 5.0,
            "currency_id": self.company.currency_id.id,
            "payment_id": "P",
            "order_uid": "O",
            "timeout": 1000,
            "attempt_number": 1,
            "cashier_name": "",
        }
        with patch.object(
            YavinPaymentValidator,
            "resolve_ip_address",
            return_value=("127.0.0.1", None),
        ), patch(
            "odoo.addons.pos_yavin.models.yavin.application."
            "payment_orchestrator.YavinAPIClient",
        ) as client_cls:
            client_instance = client_cls.return_value
            client_instance.send_payment.return_value = {"operation_status": "success"}
            result = self.env["pos.payment.method"].yavin_send_payment(payload)
        self.assertEqual(result["operation_status"], "success")
        client_instance.send_payment.assert_called_once()

    def test_yavin_abort_payment_unchanged_cloud(self):
        method = self._create_cloud_method()
        data = {
            "payment_method_id": method.id,
            "order_uid": "O",
            "payment_id": "P",
            "attempt_number": 1,
        }
        orch = method._get_yavin_orchestrator()
        with patch.object(
            orch,
            "abort_payment",
            return_value={"operation_status": "success"},
        ) as m, patch.object(type(method), "_get_yavin_orchestrator", return_value=orch):
            r = method.yavin_abort_payment(data)
        self.assertEqual(r["operation_status"], "success")
        m.assert_called_once_with(data)

    def test_yavin_send_reversal_unchanged_cloud(self):
        method = self._create_cloud_method()
        payload = {
            "payment_method_id": method.id,
            "amount": 1.0,
            "currency_id": self.company.currency_id.id,
            "order_uid": "O",
            "payment_id": "P",
            "initial_transaction_id": "TX",
        }
        orch = method._get_yavin_orchestrator()
        with patch.object(
            orch,
            "send_reversal",
            return_value={"operation_status": "success"},
        ) as m, patch.object(type(method), "_get_yavin_orchestrator", return_value=orch):
            r = method.yavin_send_reversal(payload)
        self.assertEqual(r["operation_status"], "success")
        m.assert_called_once_with(payload)

    def test_start_uuid_uniqueness_per_attempt(self):
        method = self._create_cloud_method()
        with patch(
            "odoo.addons.pos_yavin.models.yavin.application.cloud_payment.YavinCloudClient.start_payment",
            return_value={"status": "ok", "transactionId": "TA"},
        ):
            self.env["pos.payment.method"].yavin_cloud_start(
                self._base_payload(method, attempt_number=1, payment_id="PX")
            )
            self.env["pos.payment.method"].yavin_cloud_start(
                self._base_payload(method, attempt_number=2, payment_id="PX")
            )
        txs = self.env["yavin.cloud.transaction"].search(
            [("payment_method_id", "=", method.id)]
        )
        self.assertEqual(len(txs), 2)
        uuids = {t.idempotent_uuid for t in txs}
        self.assertEqual(uuids, {"O1-PX-1", "O1-PX-2"})

    def test_status_concurrent_safe_double_read(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u8",
                "cart_id": "c8",
                "currency_id": self.company.currency_id.id,
                "cloud_transaction_id": "T8",
                "state": "done",
                "result_payload": {
                    "status": "ok",
                    "trs_id": "T8",
                    "scheme": "VISA",
                    "issuer": "",
                    "client_ticket": "",
                    "gift_amount": 0,
                },
            }
        )
        r1 = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": tx.id, "payment_method_id": method.id, "expire": False}
        )
        r2 = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": tx.id, "payment_method_id": method.id, "expire": False}
        )
        self.assertEqual(r1["operation_status"], "success")
        self.assertEqual(r2["operation_status"], "success")

    def test_start_idempotent_returns_existing_tx(self):
        method = self._create_cloud_method()
        payload = self._base_payload(method, payment_id="PIDEM", order_uid="OIDEM")
        with patch(
            "odoo.addons.pos_yavin.models.yavin.application.cloud_payment.YavinCloudClient.start_payment",
            return_value={"status": "ok", "transactionId": "TIDEM"},
        ) as start_mock:
            r1 = self.env["pos.payment.method"].yavin_cloud_start(payload)
            r2 = self.env["pos.payment.method"].yavin_cloud_start(payload)
        self.assertEqual(r1["yavin_tx_id"], r2["yavin_tx_id"])
        self.assertEqual(start_mock.call_count, 1)
        self.assertEqual(
            self.env["yavin.cloud.transaction"].search_count(
                [("payment_method_id", "=", method.id)]
            ),
            1,
        )

    def test_webhook_after_timeout_recovers_payment(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u9",
                "cart_id": "C9",
                "currency_id": self.company.currency_id.id,
                "cloud_transaction_id": "T9",
                "state": "error",
                "error_message": YAVIN_TIMEOUT_ERROR_MSG,
            }
        )
        self.env["yavin.cloud.transaction"]._yavin_process_webhook(
            method.yavin_webhook_token,
            {
                "status": "ok",
                "trs_id": "T9",
                "cartId": "C9",
                "scheme": "VISA",
                "issuer": "Bank",
                "client_ticket": "OK",
                "gift_amount": 0,
            },
        )
        tx.invalidate_recordset()
        self.assertEqual(tx.state, "done")
        result = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": tx.id, "payment_method_id": method.id, "expire": False}
        )
        self.assertEqual(result["operation_status"], "success")

    def test_webhook_after_real_error_does_not_recover(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u10",
                "cart_id": "C10",
                "currency_id": self.company.currency_id.id,
                "cloud_transaction_id": "T10",
                "state": "error",
                "error_message": "Refused",
            }
        )
        self.env["yavin.cloud.transaction"]._yavin_process_webhook(
            method.yavin_webhook_token,
            {
                "status": "ok",
                "trs_id": "T10",
                "cartId": "C10",
                "client_ticket": "x",
                "gift_amount": 0,
            },
        )
        tx.invalidate_recordset()
        self.assertEqual(tx.state, "error")

    def test_status_rejects_wrong_payment_method(self):
        m_a = self._create_cloud_method("Method A")
        m_b = self._create_cloud_method("Method B")
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": m_a.id,
                "idempotent_uuid": "u11",
                "cart_id": "c",
                "currency_id": self.company.currency_id.id,
                "cloud_transaction_id": "T11",
            }
        )
        result = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": tx.id, "payment_method_id": m_b.id, "expire": False}
        )
        self.assertEqual(result["operation_status"], "issue")
        self.assertIn("Unknown transaction", result["error_message"])

    def test_status_missing_payment_method_id(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u12",
                "cart_id": "c",
                "currency_id": self.company.currency_id.id,
            }
        )
        result = self.env["pos.payment.method"].yavin_cloud_status(
            {"yavin_tx_id": tx.id, "expire": False}
        )
        self.assertEqual(result["operation_status"], "issue")

    def test_webhook_idempotent_when_already_done_twice(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u13",
                "cart_id": "C13",
                "currency_id": self.company.currency_id.id,
                "cloud_transaction_id": "T13",
            }
        )
        p1 = {
            "status": "ok",
            "trs_id": "T13",
            "cartId": "C13",
            "scheme": "VISA",
            "issuer": "",
            "client_ticket": "A",
            "gift_amount": 0,
        }
        self.env["yavin.cloud.transaction"]._yavin_process_webhook(
            method.yavin_webhook_token, p1
        )
        self.env["yavin.cloud.transaction"]._yavin_process_webhook(
            method.yavin_webhook_token,
            {**p1, "client_ticket": "B"},
        )
        tx.invalidate_recordset()
        self.assertEqual(tx.result_payload.get("client_ticket"), "A")

    def test_late_webhook_recovery_is_idempotent_on_duplicate_delivery(self):
        method = self._create_cloud_method()
        tx = self.env["yavin.cloud.transaction"].sudo().create(
            {
                "payment_method_id": method.id,
                "idempotent_uuid": "u14",
                "cart_id": "C14",
                "currency_id": self.company.currency_id.id,
                "cloud_transaction_id": "T14",
                "state": "error",
                "error_message": YAVIN_TIMEOUT_ERROR_MSG,
            }
        )
        first_payload = {
            "status": "ok",
            "trs_id": "T14",
            "cartId": "C14",
            "scheme": "VISA",
            "issuer": "Bank",
            "client_ticket": "FIRST",
            "gift_amount": 0,
        }
        self.env["yavin.cloud.transaction"]._yavin_process_webhook(
            method.yavin_webhook_token,
            first_payload,
        )
        self.env["yavin.cloud.transaction"]._yavin_process_webhook(
            method.yavin_webhook_token,
            {**first_payload, "client_ticket": "SECOND"},
        )
        tx.invalidate_recordset()
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.result_payload.get("client_ticket"), "FIRST")
