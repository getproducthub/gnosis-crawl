"""LLM provider adapters for the agent engine.

Usage:
    from app.agent.providers import create_provider, create_provider_from_config

    # By name
    provider = create_provider("openai", api_key="sk-...", model="gpt-4.1-mini")

    # From app config
    provider = create_provider_from_config()
"""

from app.agent.providers.base import (
    LLMAdapter,
    FallbackAdapter,
    create_provider,
    create_provider_from_config,
)

__all__ = [
    "LLMAdapter",
    "FallbackAdapter",
    "create_provider",
    "create_provider_from_config",
]
