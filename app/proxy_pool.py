"""
Rotating Proxy Pool for gnosis-crawl.

Manages a pool of proxies with sticky sessions per domain,
health tracking, and automatic rotation on failures.
"""

import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProxyEntry:
    """A single proxy configuration."""
    server: str
    username: Optional[str] = None
    password: Optional[str] = None
    region: Optional[str] = None
    provider: str = "direct"  # "brightdata", "oxylabs", "direct"
    fail_count: int = 0
    last_fail_ts: float = 0.0
    cooldown_seconds: float = 300.0  # 5 min cooldown after failure

    @property
    def is_healthy(self) -> bool:
        if self.fail_count == 0:
            return True
        return (time.time() - self.last_fail_ts) > self.cooldown_seconds

    def to_playwright_config(self) -> dict:
        """Return Playwright-compatible proxy dict."""
        config = {"server": self.server}
        if self.username:
            config["username"] = self.username
        if self.password:
            config["password"] = self.password
        return config


class ProxyPool:
    """Rotating proxy pool with per-domain sticky sessions and health tracking."""

    def __init__(self, proxies: Optional[List[ProxyEntry]] = None):
        self._proxies: List[ProxyEntry] = proxies or []
        self._domain_sessions: Dict[str, int] = {}  # domain -> proxy index
        self._initialized = False

        if not self._proxies:
            self._load_from_env()

    def _load_from_env(self):
        """Load proxy configuration from environment variables."""
        # Bright Data residential proxy
        brightdata_url = os.environ.get("BRIGHTDATA_PROXY_URL")
        if brightdata_url:
            self._proxies.append(ProxyEntry(
                server=brightdata_url,
                username=os.environ.get("BRIGHTDATA_PROXY_USERNAME"),
                password=os.environ.get("BRIGHTDATA_PROXY_PASSWORD"),
                provider="brightdata",
            ))

        # Direct proxy from existing config
        proxy_server = os.environ.get("PROXY_SERVER")
        if proxy_server:
            self._proxies.append(ProxyEntry(
                server=proxy_server,
                username=os.environ.get("PROXY_USERNAME"),
                password=os.environ.get("PROXY_PASSWORD"),
                provider="direct",
            ))

        self._initialized = True

    def get_proxy(self, domain: str, sticky: bool = True) -> Optional[dict]:
        """
        Get a proxy for the given domain.

        Args:
            domain: Target domain (e.g., "g2.com")
            sticky: If True, returns same proxy for same domain

        Returns:
            Playwright-compatible proxy dict or None
        """
        healthy = [i for i, p in enumerate(self._proxies) if p.is_healthy]
        if not healthy:
            return None

        if sticky and domain in self._domain_sessions:
            idx = self._domain_sessions[domain]
            if idx in healthy:
                return self._proxies[idx].to_playwright_config()
            # Current sticky proxy unhealthy, pick new one
            del self._domain_sessions[domain]

        idx = random.choice(healthy)
        if sticky:
            self._domain_sessions[domain] = idx
        return self._proxies[idx].to_playwright_config()

    def mark_failed(self, domain: str):
        """Mark the proxy assigned to this domain as failed."""
        if domain in self._domain_sessions:
            idx = self._domain_sessions[domain]
            proxy = self._proxies[idx]
            proxy.fail_count += 1
            proxy.last_fail_ts = time.time()
            del self._domain_sessions[domain]
            logger.warning(f"Proxy {proxy.server} marked failed for {domain} (count: {proxy.fail_count})")

    def mark_success(self, domain: str):
        """Reset fail count for the proxy assigned to this domain."""
        if domain in self._domain_sessions:
            idx = self._domain_sessions[domain]
            self._proxies[idx].fail_count = 0

    @property
    def pool_size(self) -> int:
        return len(self._proxies)

    @property
    def healthy_count(self) -> int:
        return sum(1 for p in self._proxies if p.is_healthy)


# Global proxy pool instance (lazy initialization)
_global_pool: Optional[ProxyPool] = None


def get_proxy_pool() -> ProxyPool:
    """Get or create the global proxy pool."""
    global _global_pool
    if _global_pool is None:
        _global_pool = ProxyPool()
    return _global_pool
