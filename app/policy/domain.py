"""Domain allowlist and private-network deny logic."""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# RFC-1918 / loopback / link-local ranges
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def extract_domain(url: str) -> Optional[str]:
    """Return the hostname from a URL, or None if unparseable."""
    try:
        return urlparse(url).hostname
    except Exception:
        return None


def is_domain_allowed(url: str, allowed_domains: List[str]) -> bool:
    """Check url against an allowlist. Empty list = allow all."""
    if not allowed_domains:
        return True
    hostname = extract_domain(url)
    if hostname is None:
        return False
    for pattern in allowed_domains:
        if hostname == pattern or hostname.endswith("." + pattern):
            return True
    return False


def resolves_to_private(hostname: str) -> bool:
    """Resolve hostname and check whether any address falls in a private range."""
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in infos:
            addr = ipaddress.ip_address(sockaddr[0])
            for net in _PRIVATE_NETWORKS:
                if addr in net:
                    logger.warning("Domain %s resolves to private address %s", hostname, addr)
                    return True
    except socket.gaierror:
        # Can't resolve — treat as non-private but log
        logger.warning("Could not resolve hostname: %s", hostname)
    return False


def check_url_policy(
    url: str,
    *,
    allowed_domains: List[str],
    block_private: bool = True,
) -> Optional[str]:
    """Return a denial reason string, or None if the URL is allowed."""
    hostname = extract_domain(url)
    if hostname is None:
        return f"Unparseable URL: {url}"

    if not is_domain_allowed(url, allowed_domains):
        return f"Domain '{hostname}' not in allowlist"

    if block_private and resolves_to_private(hostname):
        return f"Domain '{hostname}' resolves to private/loopback address"

    return None
