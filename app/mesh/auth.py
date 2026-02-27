"""HMAC token signing and verification for inter-node mesh auth.

Every mesh HTTP call carries a mesh_token. The token is an HMAC-SHA256
signature over a timestamp, so nodes sharing the same MESH_SECRET can
verify each other without a central auth service.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import logging

logger = logging.getLogger(__name__)

# Tokens are valid for 60 seconds to account for clock skew.
TOKEN_TTL_S = 60


def sign_mesh_token(secret: str, timestamp_ms: int | None = None) -> str:
    """Create an HMAC-SHA256 mesh token.

    Format: ``{timestamp_ms}.{hex_signature}``
    """
    ts = timestamp_ms or int(time.time() * 1000)
    message = str(ts).encode()
    sig = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def verify_mesh_token(token: str, secret: str) -> bool:
    """Verify an HMAC-SHA256 mesh token.

    Returns True if the signature is valid AND the timestamp is within TTL.
    """
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return False
        ts_str, sig = parts
        ts = int(ts_str)

        # Check TTL
        now = int(time.time() * 1000)
        if abs(now - ts) > TOKEN_TTL_S * 1000:
            logger.debug("Mesh token expired: age=%dms", abs(now - ts))
            return False

        # Verify signature
        expected = hmac.new(secret.encode(), ts_str.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        logger.debug("Mesh token verification failed", exc_info=True)
        return False
