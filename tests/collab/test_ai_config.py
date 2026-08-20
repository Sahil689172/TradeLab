"""API key hygiene, auth-error reporting, and startup provider validation."""

from __future__ import annotations

import httpx
import pytest

from app.collab.ai.agent import RoomAIAgent
from app.collab.ai.providers import GeminiProvider, GroqProvider
from app.collab.exceptions import AIAuthError, AIProviderError
from app.core.config import Settings


class TestApiKeyCleaning:
    """A pasted key often arrives wrapped in quotes or trailing whitespace."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('"AIzaQuoted"', "AIzaQuoted"),
            ("'AIzaSingle'", "AIzaSingle"),
            ("  AIzaPadded  ", "AIzaPadded"),
            ('"  AIzaBoth  "', "AIzaBoth"),
            ("AIzaClean", "AIzaClean"),
        ],
    )
    def test_surrounding_quotes_and_whitespace_are_stripped(
        self,
        raw: str,
        expected: str,
    ) -> None:
        settings = Settings(_env_file=None, gemini_api_key=raw, groq_api_key=raw)
        assert settings.gemini_api_key == expected
        assert settings.groq_api_key == expected

    def test_blank_key_becomes_none_so_provider_reads_unconfigured(self) -> None:
        settings = Settings(_env_file=None, gemini_api_key='  ""  ', groq_api_key="   ")
        assert settings.gemini_api_key is None
        assert settings.groq_api_key is None
        assert settings.is_ai_configured is False

    def test_quoted_key_still_produces_a_usable_provider(self) -> None:
        settings = Settings(_env_file=None, gemini_api_key='"AIzaWrapped"', groq_api_key=None)
        chain = RoomAIAgent(settings).provider_chain()
        assert [p.source.value for p in chain] == ["gemini"]


class TestKeyShapeWarning:
    """The prefix check is what catches a wrong-product key before a call."""

    def test_gemini_key_with_wrong_prefix_is_flagged(self) -> None:
        assert GeminiProvider("AQ.Ab8-not-an-ai-studio-key", "m").key_looks_valid is False
        assert GeminiProvider("AIzaLooksRight", "m").key_looks_valid is True

    def test_groq_key_with_wrong_prefix_is_flagged(self) -> None:
        assert GroqProvider("AIzaWrongProduct", "m").key_looks_valid is False
        assert GroqProvider("gsk_LooksRight", "m").key_looks_valid is True


def _auth_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        gemini_api_key="AIzaBad",
        groq_api_key=None,
        ai_enabled=True,
    )


class TestAuthErrorSurfacing:
    """A 400 from a provider must read as 'your key is wrong', not as noise."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("status", [400, 401, 403])
    async def test_auth_statuses_raise_auth_error_with_hint(
        self,
        status: int,
        patch_httpx,
    ) -> None:
        patch_httpx(
            lambda request: httpx.Response(
                status,
                json={"error": {"message": "API_KEY_INVALID", "status": "INVALID_ARGUMENT"}},
            ),
        )
        with pytest.raises(AIAuthError) as excinfo:
            await GeminiProvider("AIzaBad", "gemini-2.0-flash").validate(timeout=5.0)
        assert excinfo.value.status == status
        assert "GEMINI_API_KEY" in excinfo.value.hint

    @pytest.mark.anyio
    async def test_non_auth_status_stays_a_plain_provider_error(self, patch_httpx) -> None:
        patch_httpx(lambda request: httpx.Response(429, text="rate limited"))
        with pytest.raises(AIProviderError) as excinfo:
            await GroqProvider("gsk_ok", "llama").validate(timeout=5.0)
        assert not isinstance(excinfo.value, AIAuthError)

    @pytest.mark.anyio
    async def test_error_body_never_echoes_the_key(self, patch_httpx) -> None:
        secret = "gsk_super_secret_value"
        patch_httpx(lambda request: httpx.Response(500, text=f"upstream saw {secret}"))
        with pytest.raises(AIProviderError) as excinfo:
            await GroqProvider(secret, "llama").validate(timeout=5.0)
        assert secret not in str(excinfo.value)


class TestStatusLastError:
    """``ai/status.last_error`` is what lets the room UI name the problem."""

    @pytest.mark.anyio
    async def test_startup_validation_records_last_error(self, patch_httpx) -> None:
        patch_httpx(
            lambda request: httpx.Response(400, json={"error": {"message": "API_KEY_INVALID"}}),
        )
        agent = RoomAIAgent(_auth_settings())
        failures = await agent.validate_providers()

        assert len(failures) == 1
        status = agent.status()
        assert status.last_error is not None
        assert status.last_error.provider == "gemini"
        assert status.last_error.is_auth_error is True
        assert "GEMINI_API_KEY" in (status.last_error.hint or "")

    @pytest.mark.anyio
    async def test_startup_validation_never_raises(self, patch_httpx) -> None:
        def explode(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns is down")

        patch_httpx(explode)
        failures = await RoomAIAgent(_auth_settings()).validate_providers()
        assert [f.provider for f in failures] == ["gemini"]

    @pytest.mark.anyio
    async def test_last_error_is_clean_when_key_is_accepted(self, patch_httpx) -> None:
        patch_httpx(lambda request: httpx.Response(200, json={"models": []}))
        agent = RoomAIAgent(_auth_settings())
        assert await agent.validate_providers() == []
        assert agent.status().last_error is None

    @pytest.mark.anyio
    async def test_status_last_error_never_contains_the_key(self, patch_httpx) -> None:
        secret = "AIzaLeakMePlease"
        patch_httpx(lambda request: httpx.Response(403, text=f"denied for {secret}"))
        settings = _auth_settings().model_copy(update={"gemini_api_key": secret})
        agent = RoomAIAgent(settings)
        await agent.validate_providers()
        assert secret not in agent.status().model_dump_json()


class TestStatusEndpoint:
    def test_ai_status_exposes_last_error_field(self, client) -> None:
        response = client.get("/api/v1/collab/ai/status")
        assert response.status_code == 200
        payload = response.json()["data"]
        assert "last_error" in payload
        assert payload["read_only"] is True


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


class TestModelAvailability:
    """A retired model id is the other way a working key still fails."""

    @pytest.mark.anyio
    async def test_missing_groq_model_is_caught_at_startup(self, patch_httpx) -> None:
        patch_httpx(
            lambda request: httpx.Response(
                200,
                json={"data": [{"id": "openai/gpt-oss-120b"}, {"id": "qwen/qwen3.6-27b"}]},
            ),
        )
        provider = GroqProvider("gsk_ok", "llama-3.3-70b-versatile")
        with pytest.raises(AIProviderError) as excinfo:
            await provider.validate(timeout=5.0)
        message = str(excinfo.value)
        assert "GROQ_MODEL" in message
        assert "openai/gpt-oss-120b" in message

    @pytest.mark.anyio
    async def test_available_groq_model_passes(self, patch_httpx) -> None:
        patch_httpx(
            lambda request: httpx.Response(200, json={"data": [{"id": "openai/gpt-oss-120b"}]}),
        )
        await GroqProvider("gsk_ok", "openai/gpt-oss-120b").validate(timeout=5.0)

    @pytest.mark.anyio
    async def test_gemini_model_ids_are_compared_without_the_models_prefix(
        self,
        patch_httpx,
    ) -> None:
        patch_httpx(
            lambda request: httpx.Response(
                200,
                json={"models": [{"name": "models/gemini-2.0-flash"}]},
            ),
        )
        await GeminiProvider("AIzaOk", "gemini-2.0-flash").validate(timeout=5.0)

    @pytest.mark.anyio
    async def test_a_dead_model_lands_in_status_last_error(self, patch_httpx) -> None:
        patch_httpx(
            lambda request: httpx.Response(200, json={"data": [{"id": "openai/gpt-oss-120b"}]}),
        )
        settings = Settings(
            _env_file=None,
            app_env="test",
            gemini_api_key=None,
            groq_api_key="gsk_ok",
            groq_model="llama-3.3-70b-versatile",
            ai_enabled=True,
        )
        agent = RoomAIAgent(settings)
        failures = await agent.validate_providers()
        assert [f.provider for f in failures] == ["groq"]
        assert "GROQ_MODEL" in agent.status().last_error.reason
