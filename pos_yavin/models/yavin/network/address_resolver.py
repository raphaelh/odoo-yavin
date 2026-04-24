# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Address resolver for Yavin payment terminals (IP and Bonjour/mDNS)."""

import logging
import socket
import time

from odoo import _
from odoo.exceptions import ValidationError

from ..constants import ZEROCONF_AVAILABLE
from .service_listener import YavinServiceListener

logger = logging.getLogger(__name__)

if ZEROCONF_AVAILABLE:
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:
        logger.warning("zeroconf library available but ServiceBrowser/Zeroconf import failed.")
        ZEROCONF_AVAILABLE = False
else:
    logger.warning("zeroconf library not available. Bonjour discovery will not work.")


class YavinAddressResolver:
    """Resolver for Yavin payment terminal addresses (IP or Bonjour/mDNS)."""
    # pylint: disable=too-few-public-methods

    def __init__(self, env):
        self.env = env

    def resolve_address(self, address):  # pylint: disable=too-many-branches,too-many-statements
        """
        Resolve an IP address or Bonjour/mDNS name to an IP address.

        :param address: IP address (IPv4 or IPv6) or Bonjour/mDNS name
        :return: Resolved IP address (IPv4 preferred, else IPv6)
        :raises ValidationError: If the address cannot be resolved
        """
        if not address:
            raise ValidationError(_("Address is empty"))

        address = address.strip()

        # Check if it's an IPv4 address
        try:
            socket.inet_aton(address)
            logger.debug("Address '%s' is a valid IPv4 address", address)
            return address
        except OSError:
            logger.debug("Address '%s' is not a valid IPv4 address", address)

        # Check if it's an IPv6 address
        try:
            socket.inet_pton(socket.AF_INET6, address)
            logger.debug("Address '%s' is a valid IPv6 address", address)
            return address
        except OSError:
            logger.debug("Address '%s' is not a valid IPv6 address", address)

        # Not an IP, try to resolve via Bonjour/mDNS
        logger.debug("Address '%s' is not an IP, attempting Bonjour/mDNS resolution", address)

        if not ZEROCONF_AVAILABLE:
            raise ValidationError(
                _(
                    "Cannot resolve Bonjour name '%(name)s': zeroconf library is not "
                    "installed. Please install it with: pip install zeroconf, or use an "
                    "IP address instead.",
                    name=address,
                )
            )

        # Build full service name
        # Name can be provided with or without ._yavin._tcp.local. suffix
        if address.endswith("._yavin._tcp.local."):
            service_name = address
        elif address.endswith("._yavin._tcp.local"):
            service_name = address + "."
        else:
            service_name = f"{address}._yavin._tcp.local."

        service_type = "_yavin._tcp.local."

        try:
            zc = Zeroconf()
            try:
                # Try to get service information
                info = zc.get_service_info(service_type, service_name)

                if not info:
                    # If service not found with full name,
                    # try to discover it by browsing all services
                    logger.debug(
                        "Service '%s' not found directly, attempting discovery",
                        service_name
                    )

                    # Create temporary listener to discover the service
                    listener = YavinServiceListener()
                    browser = ServiceBrowser(zc, service_type, listener)

                    # Wait a bit for discovery
                    time.sleep(2)

                    # Search for the service in discovered services
                    with listener.lock:
                        for service in listener.services:
                            if service["name"] == address:
                                # Found! Extract IP
                                if service["ipv4_addresses"]:
                                    ip_address = service["ipv4_addresses"][0]
                                elif service["ipv6_addresses"]:
                                    ip_address = service["ipv6_addresses"][0]
                                else:
                                    browser.cancel()
                                    zc.close()
                                    raise ValidationError(
                                        _(
                                            "Bonjour service '%(name)s' found but has no "
                                            "IP address",
                                            name=address,
                                        )
                                    )

                                browser.cancel()
                                zc.close()
                                logger.info(
                                    "Resolved Bonjour name '%s' to IP address '%s'",
                                    address,
                                    ip_address
                                )
                                return ip_address

                    browser.cancel()
                    zc.close()
                    raise ValidationError(
                        _(
                            "Bonjour service '%(name)s' not found. "
                            "Please check that the terminal is powered on and connected "
                            "to the network, or use an IP address instead.",
                            name=address
                        )
                    )

                # Service found directly, extract IP
                ipv4_addresses = []
                ipv6_addresses = []

                for addr in info.addresses:
                    if len(addr) == 4:
                        # IPv4
                        ip = socket.inet_ntoa(addr)
                        ipv4_addresses.append(ip)
                    elif len(addr) == 16:
                        # IPv6
                        ip = socket.inet_ntop(socket.AF_INET6, addr)
                        ipv6_addresses.append(ip)

                # Prefer IPv4, else IPv6
                if ipv4_addresses:
                    ip_address = ipv4_addresses[0]
                elif ipv6_addresses:
                    ip_address = ipv6_addresses[0]
                else:
                    zc.close()
                    raise ValidationError(
                        _(
                            "Bonjour service '%(name)s' found but has no "
                            "IP address",
                            name=address,
                        )
                    )

                zc.close()
                logger.info(
                    "Resolved Bonjour name '%s' to IP address '%s'",
                    address,
                    ip_address
                )
                return ip_address

            except Exception as e:
                zc.close()
                if isinstance(e, ValidationError):
                    raise
                raise ValidationError(
                    _(
                        "Error resolving Bonjour name '%(name)s': %(error)s",
                        name=address,
                        error=str(e)
                    )
                ) from e
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            raise ValidationError(
                _(
                    "Error initializing Bonjour resolver for '%(name)s': %(error)s",
                    name=address,
                    error=str(e)
                )
            ) from e
