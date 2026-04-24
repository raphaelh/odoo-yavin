# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for Bonjour/mDNS service listener."""

# pylint: disable=import-error,missing-function-docstring,invalid-name

import socket
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.addons.pos_yavin.models.yavin.network.service_listener import (
    YavinServiceListener,
)


class TestYavinServiceListener(TransactionCase):
    """Tests for :class:`YavinServiceListener`."""
    def test_add_service_collects_addresses_and_normalizes_name(self):
        listener = YavinServiceListener()
        info = MagicMock()
        info.addresses = [
            socket.inet_aton("192.168.1.20"),
            socket.inet_pton(socket.AF_INET6, "2001:db8::20"),
        ]
        info.port = 16125
        zc = MagicMock()
        zc.get_service_info.return_value = info

        listener.add_service(zc, "_yavin._tcp.local.", "TerminalA._yavin._tcp.local.")

        self.assertEqual(
            listener.services,
            [
                {
                    "name": "TerminalA",
                    "ipv4_addresses": ["192.168.1.20"],
                    "ipv6_addresses": ["2001:db8::20"],
                    "port": 16125,
                }
            ],
        )

    def test_add_service_ignores_missing_service_info(self):
        listener = YavinServiceListener()
        zc = MagicMock()
        zc.get_service_info.return_value = None

        listener.add_service(zc, "_yavin._tcp.local.", "Missing._yavin._tcp.local.")

        self.assertEqual(listener.services, [])

    def test_update_service_reuses_add_service_logic(self):
        listener = YavinServiceListener()

        with patch.object(listener, "add_service") as add_service:
            listener.update_service(
                MagicMock(),
                "_yavin._tcp.local.",
                "TerminalB._yavin._tcp.local.",
            )

        add_service.assert_called_once()

    def test_add_service_ignores_unknown_address_length(self):
        listener = YavinServiceListener()
        info = MagicMock()
        info.addresses = [b"\x01\x02\x03"]  # invalid length, neither IPv4 nor IPv6
        info.port = 16125
        zc = MagicMock()
        zc.get_service_info.return_value = info

        listener.add_service(zc, "_yavin._tcp.local.", "TerminalC._yavin._tcp.local.")

        self.assertEqual(listener.services[0]["name"], "TerminalC")
        self.assertEqual(listener.services[0]["ipv4_addresses"], [])
        self.assertEqual(listener.services[0]["ipv6_addresses"], [])

    def test_add_service_normalizes_short_suffix_name(self):
        listener = YavinServiceListener()
        info = MagicMock()
        info.addresses = [socket.inet_aton("10.0.0.8")]
        info.port = 16125
        zc = MagicMock()
        zc.get_service_info.return_value = info

        listener.add_service(zc, "_yavin._tcp.local.", "TerminalD._yavin._tcp.")

        self.assertEqual(listener.services[0]["name"], "TerminalD")

    def test_remove_service_is_noop(self):
        listener = YavinServiceListener()
        listener.services.append({"name": "Keep"})
        listener.remove_service(MagicMock(), "_yavin._tcp.local.", "TerminalX._yavin._tcp.local.")
        self.assertEqual(listener.services, [{"name": "Keep"}])
