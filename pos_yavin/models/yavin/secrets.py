"""Helpers to validate and redact sensitive Yavin values."""

import re

_REDACTED = "[REDACTED]"
_PLACEHOLDER_API_KEYS = {
    "changeme",
    "change_me",
    "your_api_key",
    "your-api-key",
    "api_key",
    "apikey",
    "secret",
    "test",
    "demo",
    "xxxxxxxx",
}


def normalize_secret(value):
    """Return a trimmed secret value."""
    return (value or "").strip()


def is_valid_cloud_api_key(value):
    """Reject empty values and known placeholders."""
    normalized = normalize_secret(value)
    return bool(normalized and normalized.lower() not in _PLACEHOLDER_API_KEYS)


def redact_text(text, secrets=()):
    """Redact explicit secrets and common API key patterns."""
    redacted = text or ""
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, _REDACTED)

    # Header-style leaks
    redacted = re.sub(
        r'(?i)(yavin-secret\s*[:=]\s*)["\']?([^,"\'}\s]+)',
        rf"\1{_REDACTED}",
        redacted,
    )
    # JSON-like leaks
    redacted = re.sub(
        r'(?i)("?(?:api[_-]?key|yavin[_-]?secret)"?\s*:\s*)["\']([^"\']+)["\']',
        rf'\1"{_REDACTED}"',
        redacted,
    )
    return redacted


def redact_payload(data, secrets=()):
    """Redact sensitive values in nested dict/list payloads."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_name = str(key).lower()
            if key_name in {"api_key", "apikey", "yavin-secret", "yavin_secret"}:
                result[key] = _REDACTED
            else:
                result[key] = redact_payload(value, secrets=secrets)
        return result
    if isinstance(data, list):
        return [redact_payload(item, secrets=secrets) for item in data]
    if isinstance(data, str):
        return redact_text(data, secrets=secrets)
    return data
