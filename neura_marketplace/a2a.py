from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentCapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False


class AgentCard(BaseModel):
    """A2A discovery card served at /.well-known/agent.json."""

    agent_id: str
    name: str
    description: str
    division: str
    vibe: str | None = None
    tools: list[str] = Field(default_factory=list)
    endpoint: str
    auth_required: bool = False
    # A2A protocol spec fields (extensions beyond the spec keep their own names).
    protocol_version: str = "0.3.0"
    preferred_transport: str = "JSONRPC"
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[dict[str, str]] = Field(default_factory=list)


def text_from_message(message: Any) -> str:
    """Extract text from an A2A-style message body ({"parts": [{"text": ...}]})."""
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, dict):
        parts = message.get("parts") or []
        texts = [str(part.get("text", "")) for part in parts if isinstance(part, dict)]
        return "\n".join(text for text in texts if text).strip()
    return ""


class JSONRPCRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: str | int = 1


class JSONRPCResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    id: str | int | None = None


class AgentSearchRequest(BaseModel):
    query: str
    limit: int = 5
    exclude: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
