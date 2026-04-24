# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Service listener for Yavin payment terminal discovery via Bonjour/mDNS."""

import logging
import socket
import threading

from ..constants import ZEROCONF_AVAILABLE

logger = logging.getLogger(__name__)

if ZEROCONF_AVAILABLE:
    try:
        from zeroconf import ServiceListener
    except ImportError:
        logger.warning("zeroconf library available but ServiceListener import failed.")
        ServiceListener = object
else:
    ServiceListener = object  # Fallback for inheritance
    logger.warning("zeroconf library not available. Bonjour discovery will not work.")


class YavinServiceListener(ServiceListener):
    """Listener for Yavin service discovery via Bonjour/mDNS."""

    def __init__(self):
        self.services = []
        self.lock = threading.Lock()

    def add_service(self, zc, type_, name):
        """Handle service addition (``type_`` matches zeroconf ServiceListener API)."""
        info = zc.get_service_info(type_, name)
        if info:
            with self.lock:
                # Collect all addresses (IPv4 and IPv6)
                ipv4_addresses = []
                ipv6_addresses = []
                for addr in info.addresses:
                    # Check if it's IPv4 (4 bytes) or IPv6 (16 bytes)
                    if len(addr) == 4:
                        # IPv4
                        ip = socket.inet_ntoa(addr)
                        ipv4_addresses.append(ip)
                    elif len(addr) == 16:
                        # IPv6
                        ip = socket.inet_ntop(socket.AF_INET6, addr)
                        ipv6_addresses.append(ip)

                # Clean service name (remove prefix/suffix)
                clean_name = name.replace("._yavin._tcp.local.", "").replace(
                    "._yavin._tcp.", ""
                )

                # Store all addresses to allow deduplication later
                self.services.append({
                    "name": clean_name,
                    "ipv4_addresses": ipv4_addresses,
                    "ipv6_addresses": ipv6_addresses,
                    "port": info.port,
                })

    def remove_service(self, zc, type_, name):  # pylint: disable=unused-argument
        """Handle service removal (ignored for discovery)."""

    def update_service(self, zc, type_, name):
        """Handle service update (``type_`` matches zeroconf ServiceListener API)."""
        self.add_service(zc, type_, name)
