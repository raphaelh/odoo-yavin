# Copyright 2026 Raphaël HUCK
# @author: Raphaël HUCK
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Constants for Yavin payment terminal integration."""

# Supported currencies for Yavin
SUPPORTED_CURRENCIES = ["EUR", "CHF", "GBP"]

# Yavin API configuration
YAVIN_API_PORT = 16125
YAVIN_API_PAYMENT_ENDPOINT = "/localapi/v4/payment"
YAVIN_API_ABORT_ENDPOINT = "/localapi/v4/abort"
YAVIN_API_REVERSAL_ENDPOINT = "/localapi/v4/reversal"

# Yavin Cloud API (HTTPS, api.yavin.com)
YAVIN_CLOUD_API_BASE_URL = "https://api.yavin.com"
YAVIN_CLOUD_PAYMENT_PATH = "/api/v4/pos/payment/"
YAVIN_CLOUD_ABORT_PATH = "/api/v4/pos/abort/"
YAVIN_CLOUD_REVERSAL_PATH = "/api/v4/pos/reversal/"
# Yavin Pay has two timeouts:
# - 60 seconds for pre-payment phase (tip selection, reference, etc.)
# - 60 seconds for post-payment phase (customer feedback, loyalty, receipt, etc.)
# Total: 120 seconds + 4 seconds margin = 124 seconds for payment requests
YAVIN_DEFAULT_TIMEOUT_MS = 124000

# Sentinel stored on yavin.cloud.transaction when the POS deadline expires before
# the webhook. Used to allow _yavin_process_webhook to recover a late success.
YAVIN_TIMEOUT_ERROR_MSG = "yavin:timeout:webhook"

# Reversal timeout: 62 seconds (no pre-payment timeout)
YAVIN_REVERSAL_TIMEOUT_MS = 62000

# Abort responses should be much faster (terminal usually replies within a second).
# Using a 10-second timeout keeps the UX snappy while leaving margin for retries
# and occasional network hiccups.
YAVIN_ABORT_TIMEOUT_SEC = 10

# Wait time after receiving first response to allow second response to arrive
# when payment and abort requests are sent simultaneously (non-deterministic order)
# 100ms is imperceptible to users (< perception threshold of 100-200ms)
YAVIN_RESPONSE_WAIT_TIME_MS = 100

try:
    import zeroconf  # pylint: disable=unused-import
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False
