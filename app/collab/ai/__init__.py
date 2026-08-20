"""Grounded AI assistant for collaborative rooms."""

from app.collab.ai.agent import RoomAIAgent, get_room_ai_agent, is_ai_invocation, strip_trigger
from app.collab.ai.providers import GeminiProvider, GroqProvider, LLMProvider
from app.collab.ai.tools import TOOL_SPECS, ToolContext, execute_tool

__all__ = [
    "RoomAIAgent",
    "get_room_ai_agent",
    "is_ai_invocation",
    "strip_trigger",
    "GeminiProvider",
    "GroqProvider",
    "LLMProvider",
    "TOOL_SPECS",
    "ToolContext",
    "execute_tool",
]
