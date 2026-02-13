"""Ollama provider adapter.

Communicates with a local Ollama server over HTTP. Maps Ollama's
tool_calls response format to the agent's AssistantAction primitives.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.agent.providers.base import LLMAdapter
from app.agent.types import AssistantAction, Respond, ToolCall, ToolCalls

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3.1:8b-instruct"
DEFAULT_BASE_URL = "http://localhost:11434"
TIMEOUT_S = 120


class OllamaAdapter(LLMAdapter):
    """Adapter for Ollama local inference with tool calling."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: Optional[str] = None,
        **kwargs,
    ):
        self.model = model or DEFAULT_MODEL
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    # ------------------------------------------------------------------
    # complete
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> AssistantAction:
        """Call Ollama /api/chat and normalize the response."""
        ollama_messages = _convert_messages(messages)
        ollama_tools = _convert_tools(tools) if tools else None

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
        }
        if ollama_tools:
            payload["tools"] = ollama_tools

        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        msg = data.get("message", {})

        # Tool calls path
        tool_calls_raw = msg.get("tool_calls", [])
        if tool_calls_raw:
            calls = []
            for i, tc in enumerate(tool_calls_raw):
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"_raw": args}
                calls.append(ToolCall(
                    id=f"ollama_{i}",
                    name=fn.get("name", ""),
                    args=args,
                ))
            return ToolCalls(calls=calls)

        # Text response path
        text = msg.get("content", "")
        return Respond(text=text)

    # ------------------------------------------------------------------
    # vision — Ollama supports multimodal models (llava, etc.)
    # ------------------------------------------------------------------

    async def vision(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        detail: str = "low",
    ) -> str:
        """Send an image to an Ollama vision model (e.g. llava)."""
        import base64
        b64 = base64.b64encode(image_bytes).decode("ascii")

        payload = {
            "model": "llava",  # Default vision model for Ollama
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [b64],
                }
            ],
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        return data.get("message", {}).get("content", "")


# ---------------------------------------------------------------------------
# Message / tool schema conversion
# ---------------------------------------------------------------------------

def _convert_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert internal message format to Ollama format."""
    ollama_msgs = []
    for msg in messages:
        role = msg.get("role", "user")

        # Tool result → Ollama tool message
        if role == "tool":
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, default=str)
            ollama_msgs.append({
                "role": "tool",
                "content": content,
            })
            continue

        # Assistant with tool calls
        if role == "assistant" and "tool_calls" in msg:
            tc_list = []
            for tc in msg["tool_calls"]:
                tc_list.append({
                    "function": {
                        "name": tc["name"],
                        "arguments": tc.get("args", {}),
                    }
                })
            entry: Dict[str, Any] = {"role": "assistant"}
            if msg.get("content"):
                entry["content"] = msg["content"]
            entry["tool_calls"] = tc_list
            ollama_msgs.append(entry)
            continue

        # Standard messages
        ollama_msgs.append({
            "role": role,
            "content": msg.get("content", ""),
        })

    return ollama_msgs


def _convert_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert internal tool schemas to Ollama tool format."""
    ollama_tools = []
    for t in tools:
        ollama_tools.append({
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return ollama_tools
