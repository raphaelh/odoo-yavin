# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Terminal discoverer for Yavin payment terminals via Bonjour/mDNS."""

import logging
import time

from odoo import _
from odoo.exceptions import ValidationError

from ..constants import ZEROCONF_AVAILABLE
from .service_listener import YavinServiceListener

logger = logging.getLogger(__name__)

if ZEROCONF_AVAILABLE:
    from zeroconf import ServiceBrowser, Zeroconf
else:
    logger.warning("zeroconf library not available. Bonjour discovery will not work.")


class YavinTerminalDiscoverer:
    """Discoverer for Yavin payment terminals via Bonjour/mDNS."""
    # pylint: disable=too-few-public-methods

    def __init__(self, env):
        self.env = env

    def discover_terminals(self, timeout=5):
        """
        Discover Yavin payment terminals via Bonjour/mDNS.

        :param timeout: Discovery timeout in seconds (default: 5)
        :return: List of dictionaries with discovered terminals
        :raises ValidationError: If discovery fails or zeroconf is not available
        """
        if not ZEROCONF_AVAILABLE:
            raise ValidationError(
                _(
                    "zeroconf library is not installed. "
                    "Please install it with: pip install zeroconf"
                )
            )

        logger.info("Starting Yavin terminal discovery via Bonjour...")
        discovered = []

        try:
            zc = Zeroconf()
            listener = YavinServiceListener()
            browser = ServiceBrowser(zc, "_yavin._tcp.local.", listener)

            # Wait for discovery
            time.sleep(timeout)

            # Get discovered services
            with listener.lock:
                raw_services = listener.services.copy()

            # Cleanup
            browser.cancel()
            zc.close()

            # Deduplicate by terminal name and prioritize IPv4
            terminals_dict = {}
            for service in raw_services:
                service_name = service["name"]
                # If we've already seen this terminal, keep the one with IPv4 preference
                if service_name not in terminals_dict:
                    terminals_dict[service_name] = service
                else:
                    # If current service has IPv4 and existing doesn't, replace it
                    existing = terminals_dict[service_name]
                    if service["ipv4_addresses"] and not existing["ipv4_addresses"]:
                        terminals_dict[service_name] = service
                    # If both have IPv4, keep the first (already registered)
                    # If neither has IPv4, keep the first

            # Convert to final list with IP address selection
            discovered = []
            for service_name, service in terminals_dict.items():
                # Prioritize IPv4, else IPv6, else None
                if service["ipv4_addresses"]:
                    ip_address = service["ipv4_addresses"][0]  # Take first IPv4
                elif service["ipv6_addresses"]:
                    ip_address = service["ipv6_addresses"][0]  # Take first IPv6
                else:
                    continue  # No address, ignore

                discovered.append({
                    "name": service_name,
                    "ip_address": ip_address,
                    "port": service["port"],
                })

            logger.info("Yavin discovery completed. Found %d unique terminal(s)", len(discovered))
            for service in discovered:
                logger.info(
                    "  - %s at %s:%s",
                    service["name"],
                    service["ip_address"],
                    service["port"],
                )

        except Exception as e:
            logger.error("Error during Yavin terminal discovery: %s", e)
            raise ValidationError(
                _("Error discovering Yavin terminals: %(error)s", error=str(e))
            ) from e

        return discovered
