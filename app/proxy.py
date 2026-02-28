"""Proxy resolution: merges per-request proxy config with env-based defaults."""

from typing import Optional

from app.config import settings


def resolve_proxy(request_proxy=None, app_settings=None) -> Optional[dict]:
    """Merge per-request proxy with env-based default. Request takes priority."""
    s = app_settings or settings

    # Per-request proxy takes priority
    if request_proxy is not None:
        if hasattr(request_proxy, 'model_dump'):
            proxy_dict = request_proxy.model_dump(exclude_none=True)
        elif isinstance(request_proxy, dict):
            proxy_dict = {k: v for k, v in request_proxy.items() if v is not None}
        else:
            proxy_dict = None
        if proxy_dict and proxy_dict.get("server"):
            return proxy_dict

    # Fall back to env-based default
    return s.get_proxy_config()
