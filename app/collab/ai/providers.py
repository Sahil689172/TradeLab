"""LLM providers for the room assistant: Gemini (primary), Groq (fallback).

Both are called over plain HTTP with ``httpx`` — already a project
dependency — so no vendor SDK is added. Each provider owns its own
tool-calling loop because the wire formats differ enough that a shared
"neutral" message format would leak provider details anyway:

* Gemini exposes ``tools[].functionDeclarations`` and replies with
  ``parts[].functionCall``; results go back as ``parts[].functionResponse``.
* Groq is OpenAI-compatible: ``tools[].function`` and ``tool_calls``, with
  results returned as ``role: "tool"`` messages.

Neither provider is ever given a tool that can place an order.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.collab.ai.tools import TOOL_SPECS, ToolContext, execute_tool
from app.collab.exceptions import AIAuthError, AIProviderError
from app.collab.schemas import AIReply, AISource
from app.core.logging import get_logger

logger = get_logger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

#: Statuses that mean "the key is wrong", not "the service is unwell".
AUTH_STATUSES = frozenset({400, 401, 403})

#: Prefix each provider stamps on a valid key. Used only for an early
#: warning — the provider remains the authority on whether a key works.
GEMINI_KEY_PREFIX = "AIza"
GROQ_KEY_PREFIX = "gsk_"

GEMINI_AUTH_HINT = (
    "check GEMINI_API_KEY in .env: it must be an AI Studio key starting "
    "'AIza' (https://aistudio.google.com/apikey), and the Generative "
    "Language API must be enabled for that project"
)
GROQ_AUTH_HINT = (
    "check GROQ_API_KEY in .env: it must be a key starting 'gsk_' "
    "(https://console.groq.com/keys)"
)

#: How many available model ids to name when the configured one is gone.
MODEL_SUGGESTION_COUNT = 4


def model_hint(env_var: str, model: str, available: list[str]) -> str:
    """Compose an actionable hint for a model this account cannot use.

    Providers retire model ids regularly, which surfaces as a 404 on the
    first real call. Naming the ids that *do* work turns a dead end into a
    one-line edit.
    """
    suggestions = ", ".join(sorted(available)[:MODEL_SUGGESTION_COUNT])
    return (
        f"set {env_var} in .env to a model this account can use "
        f"('{model}' is not available)"
        + (f"; try one of: {suggestions}" if suggestions else "")
    )


def redact(text: str, secret: str) -> str:
    """Remove any occurrence of an API key from provider output.

    Provider error bodies are echoed into logs and into ``AIStatus``, so a
    key that appears in one must never survive the trip.
    """
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


SYSTEM_PROMPT = """You are the TradeLab room assistant.

You are talking to two people sharing one paper-trading room. They share a
single simulated portfolio, so "we", "our position", and "the book" all refer
to that shared portfolio.

Hard rules:
1. NEVER state a price, position, P&L, or portfolio number from memory. Call a
   tool and use only what it returns. If a tool says data is unavailable, say
   so plainly and suggest bootstrapping the symbol.
2. You cannot place, modify, or cancel orders. You have no such tool. If asked
   to trade, explain that a human has to place the order in the room.
3. All prices are stored END-OF-DAY history, not live ticks. Say so when a
   question depends on how current the number is.
4. This is a simulated paper-trading environment for learning. Frame answers as
   analysis and scenarios, never as a recommendation to buy or sell real
   securities, and do not promise returns.
5. Be brief. Two or three short paragraphs at most. Lead with the numbers you
   actually retrieved.
"""


def build_user_prompt(question: str, recent_context: str | None) -> str:
    """Compose the user turn, optionally prefixed with recent room chat."""
    if not recent_context:
        return question
    return (
        "Recent conversation in the room (for context only):\n"
        f"{recent_context}\n\n"
        f"Current question: {question}"
    )


class LLMProvider(ABC):
    """Common interface for a grounded, tool-calling chat provider."""

    source: AISource
    model: str

    #: Key prefix and env var names, used for early warnings and hints.
    key_prefix: str = ""
    key_env_var: str = ""
    model_env_var: str = ""
    auth_hint: str = ""

    _api_key: str

    @property
    @abstractmethod
    def configured(self) -> bool:
        """Return True when an API key is present."""

    @property
    def key_looks_valid(self) -> bool:
        """Return True when the key carries this provider's expected prefix.

        A cheap shape check only. A key can pass this and still be revoked,
        so the provider's own response remains the authority.
        """
        return bool(self._api_key) and self._api_key.startswith(self.key_prefix)

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Convert an error response into the narrowest exception available.

        Auth failures become :class:`AIAuthError` carrying a one-line fix,
        so callers can log an instruction instead of a raw JSON blob.
        """
        if response.status_code < 400:
            return
        name = self.source.value.capitalize()
        if response.status_code in AUTH_STATUSES:
            raise AIAuthError(name, response.status_code, self.auth_hint)
        body = redact(response.text[:300], self._api_key)
        raise AIProviderError(f"{name} HTTP {response.status_code}: {body}")

    def _check_model_available(self, available: list[str]) -> None:
        """Confirm the configured model is one this account can actually use.

        A retired model id fails only on the first real call, long after
        startup said the key was fine, so it is checked here too.
        """
        if available and self.model not in available:
            raise AIProviderError(
                f"{self.source.value}: "
                + model_hint(self.model_env_var, self.model, available),
            )

    @abstractmethod
    async def validate(self, timeout: float) -> None:
        """Make one cheap, token-free call to prove the key and model work.

        Raises:
            AIAuthError: The provider rejected the key.
            AIProviderError: The provider was unreachable, or the configured
                model is not available to this account.
        """

    @abstractmethod
    async def run(
        self,
        *,
        question: str,
        recent_context: str | None,
        ctx: ToolContext,
        max_iterations: int,
        timeout: float,
        max_output_tokens: int,
    ) -> AIReply:
        """Run one grounded turn, resolving any tool calls, and return a reply."""


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


def gemini_tool_declarations() -> list[dict[str, Any]]:
    """Translate the tool registry into Gemini ``functionDeclarations``."""
    return [
        {
            "functionDeclarations": [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                }
                for spec in TOOL_SPECS
            ],
        },
    ]


class GeminiProvider(LLMProvider):
    """Google Gemini via the generativelanguage REST API."""

    source = AISource.GEMINI
    key_prefix = GEMINI_KEY_PREFIX
    key_env_var = "GEMINI_API_KEY"
    model_env_var = "GEMINI_MODEL"
    auth_hint = GEMINI_AUTH_HINT

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self.model = model

    @property
    def configured(self) -> bool:
        """Return True when a Gemini API key is set."""
        return bool(self._api_key)

    async def validate(self, timeout: float) -> None:
        """List models — a free call that still exercises the key."""
        if not self.configured:
            raise AIProviderError("Gemini API key not configured")
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{GEMINI_BASE_URL}/models",
                headers={"x-goog-api-key": self._api_key},
            )
            self._raise_for_status(response)
            # Gemini reports ids as "models/gemini-2.0-flash".
            names = [
                str(m.get("name", "")).removeprefix("models/")
                for m in response.json().get("models", [])
            ]
            self._check_model_available([n for n in names if n])

    async def run(
        self,
        *,
        question: str,
        recent_context: str | None,
        ctx: ToolContext,
        max_iterations: int,
        timeout: float,
        max_output_tokens: int,
    ) -> AIReply:
        """Drive Gemini's function-calling loop until it produces text."""
        if not self.configured:
            raise AIProviderError("Gemini API key not configured")

        url = f"{GEMINI_BASE_URL}/models/{self.model}:generateContent"
        contents: list[dict[str, Any]] = [
            {
                "role": "user",
                "parts": [{"text": build_user_prompt(question, recent_context)}],
            },
        ]
        tools_used: list[str] = []

        async with httpx.AsyncClient(timeout=timeout) as client:
            for _ in range(max_iterations):
                payload = {
                    "contents": contents,
                    "tools": gemini_tool_declarations(),
                    "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": max_output_tokens,
                    },
                }
                response = await client.post(
                    url,
                    json=payload,
                    headers={"x-goog-api-key": self._api_key},
                )
                self._raise_for_status(response)
                body = response.json()

                candidates = body.get("candidates") or []
                if not candidates:
                    raise AIProviderError("Gemini returned no candidates")
                content = candidates[0].get("content") or {}
                parts = content.get("parts") or []

                calls = [p["functionCall"] for p in parts if isinstance(p, dict) and "functionCall" in p]
                if not calls:
                    text = "".join(
                        p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p
                    ).strip()
                    if not text:
                        raise AIProviderError("Gemini returned an empty response")
                    return AIReply(
                        text=text,
                        source=self.source,
                        model=self.model,
                        tools_used=tools_used,
                    )

                contents.append({"role": "model", "parts": parts})
                response_parts: list[dict[str, Any]] = []
                for call in calls:
                    name = call.get("name", "")
                    args = call.get("args") or {}
                    logger.info("Gemini tool call: %s(%s)", name, args)
                    result = execute_tool(name, args, ctx)
                    tools_used.append(name)
                    response_parts.append(
                        {"functionResponse": {"name": name, "response": result}},
                    )
                contents.append({"role": "user", "parts": response_parts})

        raise AIProviderError(
            f"Gemini did not finish within {max_iterations} tool iterations",
        )


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------


def groq_tool_declarations() -> list[dict[str, Any]]:
    """Translate the tool registry into OpenAI-style ``tools``."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in TOOL_SPECS
    ]


class GroqProvider(LLMProvider):
    """Groq via its OpenAI-compatible chat completions endpoint."""

    source = AISource.GROQ
    key_prefix = GROQ_KEY_PREFIX
    key_env_var = "GROQ_API_KEY"
    model_env_var = "GROQ_MODEL"
    auth_hint = GROQ_AUTH_HINT

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self.model = model

    @property
    def configured(self) -> bool:
        """Return True when a Groq API key is set."""
        return bool(self._api_key)

    async def validate(self, timeout: float) -> None:
        """List models — a free call that still exercises the key."""
        if not self.configured:
            raise AIProviderError("Groq API key not configured")
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            self._raise_for_status(response)
            ids = [str(m.get("id", "")) for m in response.json().get("data", [])]
            self._check_model_available([i for i in ids if i])

    async def run(
        self,
        *,
        question: str,
        recent_context: str | None,
        ctx: ToolContext,
        max_iterations: int,
        timeout: float,
        max_output_tokens: int,
    ) -> AIReply:
        """Drive Groq's tool-calling loop until it produces content."""
        if not self.configured:
            raise AIProviderError("Groq API key not configured")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(question, recent_context)},
        ]
        tools_used: list[str] = []

        async with httpx.AsyncClient(timeout=timeout) as client:
            for _ in range(max_iterations):
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "tools": groq_tool_declarations(),
                    "tool_choice": "auto",
                    "temperature": 0.2,
                    "max_tokens": max_output_tokens,
                }
                response = await client.post(
                    GROQ_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
                self._raise_for_status(response)
                body = response.json()

                choices = body.get("choices") or []
                if not choices:
                    raise AIProviderError("Groq returned no choices")
                message = choices[0].get("message") or {}
                tool_calls = message.get("tool_calls") or []

                if not tool_calls:
                    text = (message.get("content") or "").strip()
                    if not text:
                        raise AIProviderError("Groq returned an empty response")
                    return AIReply(
                        text=text,
                        source=self.source,
                        model=self.model,
                        tools_used=tools_used,
                    )

                messages.append(message)
                for call in tool_calls:
                    function = call.get("function") or {}
                    name = function.get("name", "")
                    raw_args = function.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                    except (ValueError, TypeError):
                        args = {}
                    logger.info("Groq tool call: %s(%s)", name, args)
                    result = execute_tool(name, args, ctx)
                    tools_used.append(name)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", name),
                            "name": name,
                            "content": json.dumps(result, default=str),
                        },
                    )

        raise AIProviderError(
            f"Groq did not finish within {max_iterations} tool iterations",
        )
