"""Secret redaction for logs, traces, and persisted outputs."""

from __future__ import annotations

import re
from typing import Any, Dict

# Patterns that likely contain secrets
_SECRET_PATTERNS = [
    # API keys / tokens (generic)
    re.compile(r"(?i)(api[_-]?key|token|secret|password|auth|bearer)\s*[:=]\s*\S+"),
    # AWS-style keys
    re.compile(r"AKIA[0-9A-Z]{16}"),
    # JWT tokens
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    # Private keys
    re.compile(r"-----BEGIN\s+(RSA|EC|DSA|OPENSSH)?\s*PRIVATE KEY-----"),
]

_REDACTED = "[REDACTED]"


def redact_text(text: str) -> str:
    """Replace secret-like patterns in a string."""
    if not text:
        return text
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result


def redact_dict(data: Dict[str, Any], *, depth: int = 0, max_depth: int = 10) -> Dict[str, Any]:
    """Recursively redact secret-like values in a dictionary."""
    if depth > max_depth:
        return data

    out = {}
    for key, value in data.items():
        if _is_secret_key(key):
            out[key] = _REDACTED
        elif isinstance(value, str):
            out[key] = redact_text(value)
        elif isinstance(value, dict):
            out[key] = redact_dict(value, depth=depth + 1, max_depth=max_depth)
        elif isinstance(value, list):
            out[key] = [
                redact_dict(v, depth=depth + 1, max_depth=max_depth) if isinstance(v, dict)
                else redact_text(v) if isinstance(v, str)
                else v
                for v in value
            ]
        else:
            out[key] = value
    return out


def _is_secret_key(key: str) -> bool:
    """Check if a dict key name suggests it holds a secret."""
    lower = key.lower()
    return any(
        s in lower
        for s in ("secret", "password", "token", "api_key", "apikey", "private_key", "credentials")
    )
