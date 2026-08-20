"""Room assistant: provider selection, Gemini→Groq fallback, and grounding.

``RoomAIAgent`` is the only thing routes talk to. It builds the tool
context, tries the primary provider, and falls back to the secondary one if
the primary errors, times out, or is unconfigured. A failure of both is
returned as an ``AIReply`` carrying the error rather than raising into the
websocket loop, so a dead API key never kills a room.
"""

from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.collab.ai.providers import GeminiProvider, GroqProvider, LLMProvider, redact
from app.collab.ai.tools import ToolContext
from app.collab.exceptions import (
    AIAuthError,
    AIDisabledError,
    AINotConfiguredError,
    AIProviderError,
)
from app.collab.room_service import RoomService
from app.collab.schemas import (
    AIProviderFailure,
    AIReply,
    AISource,
    AIStatus,
    MessageKind,
    utc_now,
)
from app.core.config import Settings
from app.core.logging import get_logger
from app.market_data.services.market_data_gateway import MarketDataGateway

logger = get_logger(__name__)

MAX_CONTEXT_MESSAGES = 12

#: Keeps a surfaced reason short enough to read in a UI badge.
MAX_REASON_CHARS = 200


class RoomAIAgent:
    """Grounded assistant bound to one room."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._last_error: AIProviderFailure | None = None

    # -- provider wiring -------------------------------------------------

    def _gemini(self) -> GeminiProvider:
        return GeminiProvider(
            api_key=self._settings.gemini_api_key or "",
            model=self._settings.gemini_model,
        )

    def _groq(self) -> GroqProvider:
        return GroqProvider(
            api_key=self._settings.groq_api_key or "",
            model=self._settings.groq_model,
        )

    def provider_chain(self) -> list[LLMProvider]:
        """Return configured providers in priority order.

        ``AI_PRIMARY_PROVIDER`` decides which is tried first; the other is
        the fallback. Unconfigured providers are dropped.
        """
        gemini = self._gemini()
        groq = self._groq()
        ordered: list[LLMProvider] = (
            [gemini, groq] if self._settings.ai_primary_provider == "gemini" else [groq, gemini]
        )
        return [p for p in ordered if p.configured]

    def status(self) -> AIStatus:
        """Report configuration without exposing key material."""
        chain = self.provider_chain()
        return AIStatus(
            enabled=self._settings.ai_enabled,
            primary=chain[0].source.value if chain else "none",
            fallback=chain[1].source.value if len(chain) > 1 else None,
            gemini_configured=bool(self._settings.gemini_api_key),
            groq_configured=bool(self._settings.groq_api_key),
            gemini_model=self._settings.gemini_model,
            groq_model=self._settings.groq_model,
            trigger=self._settings.ai_trigger,
            read_only=True,
            last_error=self._last_error,
        )

    # -- failure reporting -----------------------------------------------

    def _record_failure(self, provider: LLMProvider, exc: Exception) -> AIProviderFailure:
        """Store the newest provider failure for ``ai/status`` to surface.

        The reason is truncated and stripped of key material so it can be
        rendered in the room UI without leaking anything.
        """
        is_auth = isinstance(exc, AIAuthError)
        reason = redact(str(exc), provider._api_key)  # noqa: SLF001 - redaction needs the key
        failure = AIProviderFailure(
            provider=provider.source.value,
            reason=reason[:MAX_REASON_CHARS],
            hint=provider.auth_hint if is_auth else None,
            is_auth_error=is_auth,
            occurred_at=utc_now(),
        )
        self._last_error = failure
        return failure

    def clear_last_error(self) -> None:
        """Forget the recorded failure after a provider answers successfully."""
        self._last_error = None

    async def validate_providers(self) -> list[AIProviderFailure]:
        """Probe every configured provider once and log what is broken.

        Called at startup so an invalid key is obvious in the boot log rather
        than on someone's first ``@ai``. Never raises: a provider that cannot
        be reached at boot may still work later, and a dead key must not stop
        the application from serving rooms.

        Returns:
            One failure per provider that did not accept its key.
        """
        failures: list[AIProviderFailure] = []
        for provider in self.provider_chain():
            name = provider.source.value
            if not provider.key_looks_valid:
                logger.warning(
                    "%s key does not start with '%s': %s",
                    provider.key_env_var,
                    provider.key_prefix,
                    provider.auth_hint,
                )
            try:
                await provider.validate(timeout=float(self._settings.ai_timeout_seconds))
            except AIAuthError as exc:
                failures.append(self._record_failure(provider, exc))
                logger.warning("AI provider %s rejected its key: %s", name, exc.hint)
            except (AIProviderError, httpx.HTTPError) as exc:
                failures.append(self._record_failure(provider, exc))
                logger.warning("AI provider %s unreachable at startup: %s", name, exc)
            except Exception as exc:  # noqa: BLE001 - startup must never fail here
                failures.append(self._record_failure(provider, exc))
                logger.warning("AI provider %s check failed: %s", name, exc)
            else:
                logger.info("AI provider %s key accepted (model %s)", name, provider.model)
        return failures

    # -- turn execution --------------------------------------------------

    def build_context(
        self,
        *,
        room_id: str,
        gateway: MarketDataGateway,
        session: Session,
    ) -> ToolContext:
        """Bind the read-only tool surface to one room."""
        return ToolContext(
            room_id=room_id,
            gateway=gateway,
            room_service=RoomService(session),
            settings=self._settings,
        )

    def recent_context(self, room_id: str, session: Session) -> str:
        """Render the tail of room chat as plain text for the prompt."""
        service = RoomService(session)
        messages = service.history(room_id, limit=MAX_CONTEXT_MESSAGES)
        lines: list[str] = []
        for message in messages:
            if message.kind is MessageKind.SYSTEM:
                continue
            author = "AI" if message.kind is MessageKind.AI_REPLY else message.author
            lines.append(f"{author}: {message.text}")
        return "\n".join(lines[-MAX_CONTEXT_MESSAGES:])

    async def ask(
        self,
        *,
        room_id: str,
        question: str,
        gateway: MarketDataGateway,
        session: Session,
        include_context: bool = True,
    ) -> AIReply:
        """Answer one question with tool-grounded data, falling back if needed."""
        if not self._settings.ai_enabled:
            raise AIDisabledError()

        chain = self.provider_chain()
        if not chain:
            raise AINotConfiguredError()

        ctx = self.build_context(room_id=room_id, gateway=gateway, session=session)
        context = self.recent_context(room_id, session) if include_context else None

        errors: list[str] = []
        for index, provider in enumerate(chain):
            try:
                reply = await provider.run(
                    question=question,
                    recent_context=context,
                    ctx=ctx,
                    max_iterations=self._settings.ai_max_tool_iterations,
                    timeout=float(self._settings.ai_timeout_seconds),
                    max_output_tokens=self._settings.ai_max_output_tokens,
                )
                if index > 0:
                    reply = reply.model_copy(update={"fell_back": True})
                    logger.warning(
                        "AI primary failed, answered via fallback %s",
                        provider.source.value,
                    )
                else:
                    # Only a working primary clears the banner; a successful
                    # fallback still means the primary needs attention.
                    self.clear_last_error()
                return reply
            except AIAuthError as exc:
                failure = self._record_failure(provider, exc)
                errors.append(f"{provider.source.value}: {failure.reason}")
                logger.warning(
                    "AI provider %s rejected its key: %s",
                    provider.source.value,
                    exc.hint,
                )
                continue
            except (AIProviderError, httpx.HTTPError, httpx.TimeoutException) as exc:
                failure = self._record_failure(provider, exc)
                message = f"{provider.source.value}: {failure.reason}"
                errors.append(message)
                logger.warning("AI provider failed: %s", message)
                continue
            except Exception as exc:  # noqa: BLE001 - never break the room
                failure = self._record_failure(provider, exc)
                errors.append(f"{provider.source.value}: unexpected error: {failure.reason}")
                logger.exception("Unexpected AI provider failure")
                continue

        detail = " | ".join(errors)
        return AIReply(
            text=(
                "I could not reach any AI provider just now, so I am not going to "
                "guess at numbers. Your market data and portfolio tools are "
                "unaffected — try again shortly."
            ),
            source=AISource.NONE,
            model=None,
            tools_used=[],
            fell_back=len(chain) > 1,
            error=detail,
        )


_agent: RoomAIAgent | None = None


def get_room_ai_agent(settings: Settings) -> RoomAIAgent:
    """Return a process-wide agent bound to the given settings."""
    global _agent
    if _agent is None or _agent._settings is not settings:  # noqa: SLF001 - module-local cache
        _agent = RoomAIAgent(settings)
    return _agent


def reset_room_ai_agent() -> None:
    """Clear the cached agent (tests only)."""
    global _agent
    _agent = None


def is_ai_invocation(text: str, trigger: str) -> bool:
    """Return True when a message should be routed to the assistant."""
    return trigger.lower() in text.lower()


def strip_trigger(text: str, trigger: str) -> str:
    """Remove the trigger token, returning the actual question."""
    lowered = text.lower()
    token = trigger.lower()
    index = lowered.find(token)
    if index == -1:
        return text.strip()
    cleaned = (text[:index] + text[index + len(token) :]).strip()
    return cleaned or text.strip()
