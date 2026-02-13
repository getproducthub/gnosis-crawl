"""OpenAI provider adapter.

Maps OpenAI chat-completion tool_calls responses to the agent's
AssistantAction primitives.  Supports both text responses and
parallel tool calls.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from app.agent.providers.base import LLMAdapter
from app.agent.types import AssistantAction, Respond, ToolCall, ToolCalls

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4.1-mini"


class OpenAIAdapter(LLMAdapter):
    """Adapter for OpenAI chat completions with function calling."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        base_url: Optional[str] = None,
        **kwargs,
    ):
        self.model = model or DEFAULT_MODEL
        client_kwargs: Dict[str, Any] = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = AsyncOpenAI(**client_kwargs)

    # ------------------------------------------------------------------
    # complete
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> AssistantAction:
        """Call OpenAI and normalize the response."""
        oai_messages = _convert_messages(messages)
        oai_tools = _convert_tools(tools) if tools else None

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
        }
        if oai_tools:
            kwargs["tools"] = oai_tools

        response = await self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        # Tool calls path
        if msg.tool_calls:
            calls = []
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    args=args,
                ))
            return ToolCalls(calls=calls)

        # Text response path
        text = msg.content or ""
        return Respond(text=text)

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
        """Send an image to GPT-4o vision and get text back."""
        b64 = base64.b64encode(image_bytes).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": detail,
                        },
                    },
                ],
            }
        ]

        # Use gpt-4o for vision regardless of configured model
        response = await self.client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Message / tool schema conversion
# ---------------------------------------------------------------------------

def _convert_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert internal message format to OpenAI format."""
    oai_msgs = []
    for msg in messages:
        role = msg.get("role", "user")

        # Tool result messages
        if role == "tool":
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, default=str)
            oai_msgs.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": content,
            })
            continue

        # Assistant messages with tool calls
        if role == "assistant" and "tool_calls" in msg:
            tc_list = []
            for tc in msg["tool_calls"]:
                tc_list.append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("args", {})),
                    },
                })
            oai_msgs.append({
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": tc_list,
            })
            continue

        # Standard user/assistant/system messages
        oai_msgs.append({
            "role": role,
            "content": msg.get("content", ""),
        })

    return oai_msgs


def _convert_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert internal tool schemas to OpenAI function-calling format."""
    oai_tools = []
    for t in tools:
        oai_tools.append({
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return oai_tools
