# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for Yavin terminal address resolution."""

# pylint: disable=import-error,missing-function-docstring,invalid-name,protected-access

import socket
from unittest.mock import MagicMock, patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.pos_yavin.models.yavin.network.address_resolver import (
    YavinAddressResolver,
)

_ADDRESS_RESOLVER_PKG = (
    "odoo.addons.pos_yavin.models.yavin.network.address_resolver"
)


class TestYavinAddressResolver(TransactionCase):
    """Test suite for YavinAddressResolver."""

    @staticmethod
    def _assert_message_contains_any(testcase, message, fragments):
        lowered = (message or "").lower()
        testcase.assertTrue(
            any(fragment.lower() in lowered for fragment in fragments),
            msg=f"Expected one of {fragments!r} in message: {message!r}",
        )

    def setUp(self):
        super().setUp()
        self.resolver = YavinAddressResolver(self.env)

    def test_resolve_empty_address_raises(self):
        """Empty or None address raises ValidationError."""
        with self.assertRaises(ValidationError) as cm:
            self.resolver.resolve_address("")
        self._assert_message_contains_any(
            self,
            str(cm.exception),
            ("address is empty", "adresse est vide"),
        )

        with self.assertRaises(ValidationError) as cm:
            self.resolver.resolve_address(None)
        self._assert_message_contains_any(
            self,
            str(cm.exception),
            ("address is empty", "adresse est vide"),
        )

    def test_resolve_whitespace_only_raises(self):
        """Whitespace-only address raises ValidationError."""
        with self.assertRaises(ValidationError) as cm:
            self.resolver.resolve_address("   ")
        # After strip, empty string may trigger "Address is empty" or Bonjour resolution error
        msg = str(cm.exception).lower()
        self.assertTrue("empty" in msg or "error" in msg or "bonjour" in msg)

    def test_resolve_ipv4_returns_as_is(self):
        """Valid IPv4 address is returned unchanged."""
        result = self.resolver.resolve_address("127.0.0.1")
        self.assertEqual(result, "127.0.0.1")

        result = self.resolver.resolve_address("192.168.1.100")
        self.assertEqual(result, "192.168.1.100")

        result = self.resolver.resolve_address("  10.0.0.1  ")
        self.assertEqual(result, "10.0.0.1")

    def test_resolve_ipv6_returns_as_is(self):
        """Valid IPv6 address is returned unchanged."""
        result = self.resolver.resolve_address("::1")
        self.assertEqual(result, "::1")

        result = self.resolver.resolve_address("2001:db8::1")
        self.assertEqual(result, "2001:db8::1")

    def test_resolve_invalid_ip_when_zeroconf_unavailable_raises(self):
        """Invalid IP format raises when zeroconf is unavailable."""
        with patch(
            f"{_ADDRESS_RESOLVER_PKG}.ZEROCONF_AVAILABLE",
            False,
        ):
            with self.assertRaises(ValidationError) as cm:
                self.resolver.resolve_address("not-an-ip")
            self.assertIn("zeroconf", str(cm.exception).lower())

    def test_resolve_bonjour_direct_lookup_prefers_ipv4(self):
        info = MagicMock()
        info.addresses = [
            socket.inet_pton(socket.AF_INET6, "2001:db8::99"),
            socket.inet_aton("10.0.0.99"),
        ]
        zc = MagicMock()
        zc.get_service_info.return_value = info

        with patch(
            f"{_ADDRESS_RESOLVER_PKG}.ZEROCONF_AVAILABLE",
            True,
        ), patch(
            f"{_ADDRESS_RESOLVER_PKG}.Zeroconf",
            return_value=zc,
        ):
            result = self.resolver.resolve_address("terminal")

        self.assertEqual(result, "10.0.0.99")
        zc.close.assert_called_once()

    def test_resolve_bonjour_discovery_fallback_uses_listener_services(self):
        listener = MagicMock()
        listener.services = [
            {
                "name": "terminal",
                "ipv4_addresses": ["10.0.0.55"],
                "ipv6_addresses": [],
                "port": 16125,
            }
        ]
        listener.lock = MagicMock()
        listener.lock.__enter__ = MagicMock(return_value=None)
        listener.lock.__exit__ = MagicMock(return_value=None)
        browser = MagicMock()
        zc = MagicMock()
        zc.get_service_info.return_value = None

        with patch(
            f"{_ADDRESS_RESOLVER_PKG}.ZEROCONF_AVAILABLE",
            True,
        ), patch(
            f"{_ADDRESS_RESOLVER_PKG}.Zeroconf",
            return_value=zc,
        ), patch(
            f"{_ADDRESS_RESOLVER_PKG}.YavinServiceListener",
            return_value=listener,
        ), patch(
            f"{_ADDRESS_RESOLVER_PKG}.ServiceBrowser",
            return_value=browser,
        ), patch(
            f"{_ADDRESS_RESOLVER_PKG}.time.sleep"
        ):
            result = self.resolver.resolve_address("terminal")

        self.assertEqual(result, "10.0.0.55")
        browser.cancel.assert_called_once()
        zc.close.assert_called_once()

    def test_resolve_bonjour_service_without_addresses_raises(self):
        info = MagicMock()
        info.addresses = []
        zc = MagicMock()
        zc.get_service_info.return_value = info

        with patch(
            f"{_ADDRESS_RESOLVER_PKG}.ZEROCONF_AVAILABLE",
            True,
        ), patch(
            f"{_ADDRESS_RESOLVER_PKG}.Zeroconf",
            return_value=zc,
        ):
            with self.assertRaises(ValidationError) as cm:
                self.resolver.resolve_address("terminal")

        self._assert_message_contains_any(
            self,
            str(cm.exception),
            ("no ip address", "sans adresse ip"),
        )

    def test_resolve_bonjour_initialization_error_is_wrapped(self):
        with patch(
            f"{_ADDRESS_RESOLVER_PKG}.ZEROCONF_AVAILABLE",
            True,
        ), patch(
            f"{_ADDRESS_RESOLVER_PKG}.Zeroconf",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(ValidationError) as cm:
                self.resolver.resolve_address("terminal")

        self._assert_message_contains_any(
            self,
            str(cm.exception),
            ("error initializing bonjour resolver", "initialisation du résolveur bonjour"),
        )
