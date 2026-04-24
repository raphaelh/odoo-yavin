# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Yavin payment terminal services and utilities."""

# Constants
from .constants import (
    SUPPORTED_CURRENCIES,
    YAVIN_API_ABORT_ENDPOINT,
    YAVIN_API_PAYMENT_ENDPOINT,
    YAVIN_API_PORT,
    YAVIN_ABORT_TIMEOUT_SEC,
    YAVIN_DEFAULT_TIMEOUT_MS,
    YAVIN_REVERSAL_TIMEOUT_MS,
    YAVIN_RESPONSE_WAIT_TIME_MS,
    ZEROCONF_AVAILABLE,
)

# API
from .api.client import YavinAPIClient
from .api.cloud_error_mapper import YavinCloudErrorMapper
from .api.http_transport import YavinHttpTransport
from .api.operation_handlers import YavinOperationHandlers
from .api.payload_builder import YavinPayloadBuilder
from .api.response_parser import YavinResponseParser

# Application
from .application.cloud_payment import YavinCloudPaymentService
from .application.payment_orchestrator import YavinPaymentOrchestrator
from .application.refund_transaction_resolver import YavinRefundTransactionResolver

# Network
from .network.address_resolver import YavinAddressResolver
from .network.service_listener import YavinServiceListener
from .network.terminal_discoverer import YavinTerminalDiscoverer

# Formatting
from .formatting.amount_converter import YavinAmountConverter
from .formatting.card_info_formatter import YavinCardInfoFormatter
from .formatting.data_extractor import YavinDataExtractor

# Validation
from .validation import YavinPaymentValidator
from .secrets import is_valid_cloud_api_key, normalize_secret, redact_payload, redact_text

# Version
from .version.provider import YavinVersionProvider

__all__ = [
    # Constants
    "SUPPORTED_CURRENCIES",
    "YAVIN_API_ABORT_ENDPOINT",
    "YAVIN_API_PAYMENT_ENDPOINT",
    "YAVIN_API_PORT",
    "YAVIN_ABORT_TIMEOUT_SEC",
    "YAVIN_DEFAULT_TIMEOUT_MS",
    "YAVIN_REVERSAL_TIMEOUT_MS",
    "YAVIN_RESPONSE_WAIT_TIME_MS",
    # API
    "YavinAPIClient",
    "YavinCloudErrorMapper",
    "YavinHttpTransport",
    "YavinOperationHandlers",
    "YavinPayloadBuilder",
    "YavinResponseParser",
    # Application
    "YavinCloudPaymentService",
    "YavinPaymentOrchestrator",
    "YavinRefundTransactionResolver",
    # Network
    "YavinAddressResolver",
    "YavinServiceListener",
    "YavinTerminalDiscoverer",
    "ZEROCONF_AVAILABLE",
    # Formatting
    "YavinAmountConverter",
    "YavinCardInfoFormatter",
    "YavinDataExtractor",
    # Validation
    "YavinPaymentValidator",
    "is_valid_cloud_api_key",
    "normalize_secret",
    "redact_payload",
    "redact_text",
    # Version
    "YavinVersionProvider",
]
