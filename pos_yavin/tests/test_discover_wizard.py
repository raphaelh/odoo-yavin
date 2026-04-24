# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for the Yavin terminal discovery wizard."""

# pylint: disable=import-error,missing-function-docstring,invalid-name

from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestYavinDiscoverWizard(TransactionCase):
    """Test suite for Yavin discover wizard."""

    @staticmethod
    def _assert_message_contains_any(testcase, message, fragments):
        lowered = (message or "").lower()
        testcase.assertTrue(
            any(fragment.lower() in lowered for fragment in fragments),
            msg=f"Expected one of {fragments!r} in message: {message!r}",
        )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        eur = cls.env.ref("base.EUR")
        cls.company = cls.env["res.company"].create(
            {
                "name": "Yavin Wizard Test",
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
                    "name": "Yavin Bank",
                    "code": "YAVB",
                    "type": "bank",
                    "company_id": cls.company.id,
                    "currency_id": eur.id,
                }
            )
        cls.payment_method = cls.env["pos.payment.method"].create(
            {
                "name": "Yavin Wizard Method",
                "company_id": cls.company.id,
                "journal_id": cls.bank_journal.id,
                "use_payment_terminal": "yavin",
                "yavin_connection_mode": "local",
                "yavin_ip_address": "127.0.0.1",
            }
        )

    def test_action_start_discovery_success(self):
        """Discovery succeeds and populates discovered terminals."""
        wizard = self.env["yavin.discover.wizard"].create(
            {"payment_method_id": self.payment_method.id}
        )
        discovered = [
            {"name": "Terminal1", "ip_address": "192.168.1.100", "port": 16125},
        ]
        with patch.object(
            type(self.payment_method),
            "yavin_discover_terminals",
            return_value=discovered,
        ):
            result = wizard.action_start_discovery()

        self.assertTrue(result)
        self.assertFalse(wizard.is_discovering)
        self.assertEqual(wizard.discovery_progress, 100.0)
        self.assertEqual(len(wizard.discovered_terminals), 1)
        self.assertEqual(wizard.discovered_terminals[0].name, "Terminal1")
        self.assertEqual(wizard.discovered_terminals[0].ip_address, "192.168.1.100")

    def test_action_start_discovery_no_terminals_found(self):
        """Discovery with no terminals found updates message."""
        wizard = self.env["yavin.discover.wizard"].create(
            {"payment_method_id": self.payment_method.id}
        )
        with patch.object(
            type(self.payment_method),
            "yavin_discover_terminals",
            return_value=[],
        ):
            result = wizard.action_start_discovery()

        self.assertTrue(result)
        self.assertFalse(wizard.is_discovering)
        self._assert_message_contains_any(
            self,
            wizard.discovery_message,
            ("no terminal found", "aucun terminal trouv"),
        )

    def test_action_start_discovery_multiple_terminals_message(self):
        wizard = self.env["yavin.discover.wizard"].create(
            {"payment_method_id": self.payment_method.id}
        )
        discovered = [
            {"name": "TerminalB", "ip_address": "192.168.1.101", "port": 16125},
            {"name": "TerminalA", "ip_address": "192.168.1.100", "port": 16125},
        ]
        with patch.object(
            type(self.payment_method),
            "yavin_discover_terminals",
            return_value=discovered,
        ):
            result = wizard.action_start_discovery()

        self.assertTrue(result)
        self._assert_message_contains_any(
            self,
            wizard.discovery_message,
            ("2 terminals found", "2 terminaux trouv"),
        )
        # Sorted by IP address
        self.assertEqual(wizard.discovered_terminals[0].name, "TerminalA")

    def test_action_start_discovery_validation_error_sets_message(self):
        """Backend validation errors are surfaced in the wizard state."""
        wizard = self.env["yavin.discover.wizard"].create(
            {"payment_method_id": self.payment_method.id}
        )
        with patch.object(
            type(self.payment_method),
            "yavin_discover_terminals",
            side_effect=ValidationError("zeroconf is not installed"),
        ):
            result = wizard.action_start_discovery()

        self.assertFalse(result)
        self.assertFalse(wizard.is_discovering)
        self.assertIn("zeroconf", wizard.discovery_message.lower())

    def test_action_start_discovery_payment_method_deleted(self):
        """Discovery fails when payment method no longer exists."""
        wizard = self.env["yavin.discover.wizard"].create(
            {"payment_method_id": self.payment_method.id}
        )
        self.payment_method.unlink()
        self.env.invalidate_all()

        result = wizard.action_start_discovery()
        self.assertFalse(result)
        self.assertTrue(
            "no longer exists" in wizard.discovery_message
            or "deleted" in wizard.discovery_message.lower()
        )

    def test_action_start_discovery_payment_method_exists_check_fails(self):
        wizard = self.env["yavin.discover.wizard"].create(
            {"payment_method_id": self.payment_method.id}
        )
        with patch.object(type(self.payment_method), "exists", return_value=False):
            result = wizard.action_start_discovery()
        self.assertFalse(result)
        self._assert_message_contains_any(
            self,
            wizard.discovery_message,
            ("no longer exists", "n'existe plus"),
        )

    def test_action_start_discovery_unexpected_exception_sets_error(self):
        wizard = self.env["yavin.discover.wizard"].create(
            {"payment_method_id": self.payment_method.id}
        )
        with patch.object(
            type(self.payment_method),
            "yavin_discover_terminals",
            side_effect=RuntimeError("boom"),
        ):
            result = wizard.action_start_discovery()
        self.assertFalse(result)
        self.assertIn("boom", wizard.discovery_message)

    def test_action_select_success(self):
        """Selecting a terminal updates payment method with Bonjour hostname."""
        wizard = self.env["yavin.discover.wizard"].create(
            {
                "payment_method_id": self.payment_method.id,
                "is_discovering": False,
                "discovered_terminals": [
                    (0, 0, {"name": "Terminal1", "ip_address": "192.168.1.50", "port": 16125}),
                ],
            }
        )
        terminal = wizard.discovered_terminals[0]
        result = terminal.action_select()

        self.assertEqual(result["type"], "ir.actions.act_window_close")
        self.assertEqual(self.payment_method.yavin_ip_address, "Terminal1")

    def test_action_select_no_payment_method_raises(self):
        """Selecting with no payment method raises UserError."""
        wizard = self.env["yavin.discover.wizard"].new({"payment_method_id": False})
        terminal = self.env["yavin.discover.wizard.terminal"].new({
            "wizard_id": wizard.id,
            "name": "T1",
            "ip_address": "1.1.1.1"
        })
        with self.assertRaises(UserError) as cm:
            terminal.action_select()
        self._assert_message_contains_any(
            self,
            str(cm.exception),
            ("no payment method selected", "aucune méthode de paiement sélectionnée"),
        )

    def test_action_retry_discovery_resets_state(self):
        """Retry resets wizard state and returns reload action."""
        wizard = self.env["yavin.discover.wizard"].create(
            {
                "payment_method_id": self.payment_method.id,
                "is_discovering": False,
                "discovery_message": "Done",
                "discovery_progress": 100.0,
            }
        )
        result = wizard.action_retry_discovery()

        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["tag"], "reload")
        self.assertTrue(wizard.is_discovering)
        self.assertEqual(wizard.discovery_progress, 0.0)
        self._assert_message_contains_any(
            self,
            wizard.discovery_message,
            ("search", "recherche"),
        )

    def test_action_retry_discovery_without_payment_method_raises(self):
        wizard = self.env["yavin.discover.wizard"].new({"payment_method_id": False})
        with self.assertRaises(UserError):
            wizard.action_retry_discovery()

    def test_action_select_payment_method_deleted_raises(self):
        wizard = self.env["yavin.discover.wizard"].create(
            {
                "payment_method_id": self.payment_method.id,
                "discovered_terminals": [
                    (0, 0, {"name": "Terminal1", "ip_address": "192.168.1.50", "port": 16125}),
                ],
            }
        )
        terminal = wizard.discovered_terminals[0]
        self.payment_method.unlink()
        with self.assertRaises(UserError):
            terminal.action_select()

    def test_action_select_payment_method_exists_check_fails(self):
        wizard = self.env["yavin.discover.wizard"].create(
            {
                "payment_method_id": self.payment_method.id,
                "discovered_terminals": [
                    (0, 0, {"name": "Terminal1", "ip_address": "192.168.1.50", "port": 16125}),
                ],
            }
        )
        terminal = wizard.discovered_terminals[0]
        with patch.object(type(self.payment_method), "exists", return_value=False):
            with self.assertRaises(UserError):
                terminal.action_select()

    def test_action_select_missing_terminal_name_or_ip_raises(self):
        wizard = self.env["yavin.discover.wizard"].create(
            {"payment_method_id": self.payment_method.id}
        )
        terminal_no_name = self.env["yavin.discover.wizard.terminal"].new(
            {"wizard_id": wizard.id, "name": "", "ip_address": "1.2.3.4"}
        )
        with self.assertRaises(UserError):
            terminal_no_name.action_select()

        terminal_no_ip = self.env["yavin.discover.wizard.terminal"].new(
            {"wizard_id": wizard.id, "name": "Terminal1", "ip_address": ""}
        )
        with self.assertRaises(UserError):
            terminal_no_ip.action_select()
