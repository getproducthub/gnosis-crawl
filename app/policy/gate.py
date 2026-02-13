"""Pre-tool and pre-fetch policy gates.

Every tool call and every URL fetch passes through these gates before execution.
A denied action returns a PolicyVerdict with `allowed=False` and a reason string.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.agent.types import RunConfig, ToolCall
from app.policy.domain import check_url_policy

logger = logging.getLogger(__name__)


@dataclass
class PolicyVerdict:
    allowed: bool
    reason: Optional[str] = None
    flags: List[str] = None

    def __post_init__(self):
        if self.flags is None:
            self.flags = []


def check_tool_call(call: ToolCall, config: RunConfig) -> PolicyVerdict:
    """Gate a tool call before dispatch.

    Checks:
    1. Tool is in the allowed_tools list (if non-empty).
    2. Any URL args pass domain + private-range checks.
    """
    flags: List[str] = []

    # Tool allowlist
    if config.allowed_tools and call.name not in config.allowed_tools:
        return PolicyVerdict(
            allowed=False,
            reason=f"Tool '{call.name}' not in allowed_tools",
            flags=["tool_blocked"],
        )

    # Scan args for URL-like values
    url_keys = {"url", "urls", "target_url", "href"}
    for key, value in call.args.items():
        urls = _extract_urls(key, value, url_keys)
        for url in urls:
            denial = check_url_policy(
                url,
                allowed_domains=config.allowed_domains,
                block_private=config.block_private_ranges,
            )
            if denial:
                return PolicyVerdict(allowed=False, reason=denial, flags=["url_blocked"])

    return PolicyVerdict(allowed=True, flags=flags)


def check_fetch_url(url: str, config: RunConfig) -> PolicyVerdict:
    """Gate a raw URL fetch (used by crawl tools before requesting)."""
    denial = check_url_policy(
        url,
        allowed_domains=config.allowed_domains,
        block_private=config.block_private_ranges,
    )
    if denial:
        return PolicyVerdict(allowed=False, reason=denial, flags=["url_blocked"])
    return PolicyVerdict(allowed=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_urls(key: str, value: Any, url_keys: set) -> List[str]:
    """Pull URL strings from a tool arg value."""
    if key.lower() not in url_keys:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []
