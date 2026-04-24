# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for Yavin terminal discovery via Bonjour/mDNS."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,protected-access

from unittest.mock import MagicMock, patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.pos_yavin.models.yavin.network.terminal_discoverer import (
    YavinTerminalDiscoverer,
)

_TERMINAL_DISCOVERER_PKG = (
    "odoo.addons.pos_yavin.models.yavin.network.terminal_discoverer"
)


class TestYavinTerminalDiscoverer(TransactionCase):
    """Test suite for YavinTerminalDiscoverer."""

    @staticmethod
    def _assert_message_contains_any(testcase, message, fragments):
        lowered = (message or "").lower()
        testcase.assertTrue(
            any(fragment.lower() in lowered for fragment in fragments),
            msg=f"Expected one of {fragments!r} in message: {message!r}",
        )

    def setUp(self):
        super().setUp()
        self.discoverer = YavinTerminalDiscoverer(self.env)

    def test_discover_terminals_when_zeroconf_unavailable_raises(self):
        """Discovery raises ValidationError when zeroconf is not installed."""
        with patch(
            f"{_TERMINAL_DISCOVERER_PKG}.ZEROCONF_AVAILABLE",
            False,
        ):
            with self.assertRaises(ValidationError) as cm:
                self.discoverer.discover_terminals(timeout=1)
            self.assertIn("zeroconf", str(cm.exception).lower())

    def test_discover_terminals_with_mocked_zeroconf_returns_terminals(self):
        """Discovery returns list of terminals when zeroconf is mocked."""
        mock_services = [
            {
                "name": "YavinTerminal1",
                "ipv4_addresses": ["192.168.1.100"],
                "ipv6_addresses": [],
                "port": 16125,
            },
        ]

        mock_listener = MagicMock()
        mock_listener.services = mock_services
        mock_listener.lock = MagicMock()
        mock_listener.lock.__enter__ = MagicMock(return_value=None)
        mock_listener.lock.__exit__ = MagicMock(return_value=None)

        with patch(
            f"{_TERMINAL_DISCOVERER_PKG}.ZEROCONF_AVAILABLE",
            True,
        ), patch(
            f"{_TERMINAL_DISCOVERER_PKG}.Zeroconf",
        ) as mock_zc_cls, patch(
            f"{_TERMINAL_DISCOVERER_PKG}.ServiceBrowser",
        ), patch(
            f"{_TERMINAL_DISCOVERER_PKG}.YavinServiceListener",
            return_value=mock_listener,
        ), patch(
            f"{_TERMINAL_DISCOVERER_PKG}.time.sleep",
        ):
            mock_zc = MagicMock()
            mock_zc_cls.return_value = mock_zc

            result = self.discoverer.discover_terminals(timeout=0)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "YavinTerminal1")
        self.assertEqual(result[0]["ip_address"], "192.168.1.100")
        self.assertEqual(result[0]["port"], 16125)

    def test_discover_terminals_deduplicates_and_prefers_ipv4(self):
        mock_listener = MagicMock()
        mock_listener.services = [
            {
                "name": "YavinTerminal1",
                "ipv4_addresses": [],
                "ipv6_addresses": ["2001:db8::1"],
                "port": 16125,
            },
            {
                "name": "YavinTerminal1",
                "ipv4_addresses": ["192.168.1.101"],
                "ipv6_addresses": [],
                "port": 16125,
            },
            {
                "name": "NoAddress",
                "ipv4_addresses": [],
                "ipv6_addresses": [],
                "port": 16125,
            },
        ]
        mock_listener.lock = MagicMock()
        mock_listener.lock.__enter__ = MagicMock(return_value=None)
        mock_listener.lock.__exit__ = MagicMock(return_value=None)

        with patch(
            f"{_TERMINAL_DISCOVERER_PKG}.ZEROCONF_AVAILABLE",
            True,
        ), patch(
            f"{_TERMINAL_DISCOVERER_PKG}.Zeroconf",
            return_value=MagicMock(),
        ), patch(
            f"{_TERMINAL_DISCOVERER_PKG}.ServiceBrowser",
            return_value=MagicMock(),
        ), patch(
            f"{_TERMINAL_DISCOVERER_PKG}.YavinServiceListener",
            return_value=mock_listener,
        ), patch(
            f"{_TERMINAL_DISCOVERER_PKG}.time.sleep",
        ):
            result = self.discoverer.discover_terminals(timeout=0)

        self.assertEqual(
            result,
            [
                {
                    "name": "YavinTerminal1",
                    "ip_address": "192.168.1.101",
                    "port": 16125,
                }
            ],
        )

    def test_discover_terminals_wraps_runtime_errors(self):
        with patch(
            f"{_TERMINAL_DISCOVERER_PKG}.ZEROCONF_AVAILABLE",
            True,
        ), patch(
            f"{_TERMINAL_DISCOVERER_PKG}.Zeroconf",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(ValidationError) as cm:
                self.discoverer.discover_terminals(timeout=0)

        self._assert_message_contains_any(
            self,
            str(cm.exception),
            ("error discovering yavin terminals", "découverte des terminaux yavin"),
        )
