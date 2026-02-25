"""Anthropic provider adapter.

Maps Anthropic Messages API tool_use / tool_result content blocks
to the agent's AssistantAction primitives.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

from app.agent.providers.base import LLMAdapter
from app.agent.types import AssistantAction, Respond, ToolCall, ToolCalls

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-3-5-sonnet-latest"
MAX_TOKENS = 4096


class AnthropicAdapter(LLMAdapter):
    """Adapter for Anthropic Messages API with tool use."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        **kwargs,
    ):
        self.model = model or DEFAULT_MODEL
        client_kwargs: Dict[str, Any] = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        self.client = AsyncAnthropic(**client_kwargs)

    # ------------------------------------------------------------------
    # complete
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> AssistantAction:
        """Call Anthropic Messages API and normalize the response."""
        system_prompt, api_messages = _convert_messages(messages)
        api_tools = _convert_tools(tools) if tools else []

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "messages": api_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if api_tools:
            kwargs["tools"] = api_tools

        response = await self.client.messages.create(**kwargs)

        # Parse content blocks
        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    args=block.input if isinstance(block.input, dict) else {},
                ))

        if tool_calls:
            return ToolCalls(calls=tool_calls)

        return Respond(text="\n".join(text_parts))

    # ------------------------------------------------------------------
    # vision
    # ------------------------------------------------------------------

    async def vision(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        detail: str = "low",
    ) -> str:
        """Send an image to Claude vision and get text back."""
        b64 = base64.b64encode(image_bytes).decode("ascii")

        # Detect actual image format from magic bytes
        media_type = "image/png"  # Playwright default
        if image_bytes[:3] == b"\xff\xd8\xff":
            media_type = "image/jpeg"
        elif image_bytes[:4] == b"\x89PNG":
            media_type = "image/png"
        elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            media_type = "image/webp"
        elif image_bytes[:3] == b"GIF":
            media_type = "image/gif"

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ]

        response = await self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=MAX_TOKENS,
            messages=messages,
        )

        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
        return "\n".join(text_parts)


# ---------------------------------------------------------------------------
# Message / tool schema conversion
# ---------------------------------------------------------------------------

def _convert_messages(
    messages: List[Dict[str, Any]],
) -> tuple[str, List[Dict[str, Any]]]:
    """Convert internal message format to Anthropic format.

    Returns:
        (system_prompt, api_messages)
    """
    system_prompt = ""
    api_msgs: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")

        # System messages → Anthropic system parameter
        if role == "system":
            system_prompt = msg.get("content", "")
            continue

        # Tool result messages → user message with tool_result content block
        if role == "tool":
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, default=str)
            api_msgs.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content,
                    }
                ],
            })
            continue

        # Assistant messages with tool calls → tool_use content blocks
        if role == "assistant" and "tool_calls" in msg:
            content_blocks: List[Dict[str, Any]] = []
            # Include any text content first
            if msg.get("content"):
                content_blocks.append({"type": "text", "text": msg["content"]})
            for tc in msg["tool_calls"]:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc.get("args", {}),
                })
            api_msgs.append({"role": "assistant", "content": content_blocks})
            continue

        # Standard user/assistant messages
        api_msgs.append({
            "role": role,
            "content": msg.get("content", ""),
        })

    return system_prompt, api_msgs


def _convert_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert internal tool schemas to Anthropic tool format."""
    api_tools = []
    for t in tools:
        api_tools.append({
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
        })
    return api_tools
