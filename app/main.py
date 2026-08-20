"""FastAPI application factory for TradeLab Quant Engine."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_v1_router, system_router
from app.core.config import Settings, get_settings
from app.core.database import init_db, reset_db_state
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.storage_paths import ensure_storage_directories
from app.middleware.request_logging import RequestLoggingMiddleware

logger = get_logger(__name__)


async def _check_ai_providers(settings: Settings) -> None:
    """Probe configured LLM providers so a bad key shows up in the boot log.

    Skipped under tests and when the assistant is off. Failures are logged
    by the agent and never propagate — rooms work fine without an assistant.
    """
    if settings.is_test or not (settings.collab_enabled and settings.ai_enabled):
        return
    if not settings.is_ai_configured:
        logger.warning(
            "AI assistant enabled but no provider key set: "
            "set GEMINI_API_KEY and/or GROQ_API_KEY in .env",
        )
        return
    try:
        from app.collab.ai.agent import get_room_ai_agent

        await get_room_ai_agent(settings).validate_providers()
    except Exception:  # noqa: BLE001 - a provider check must never block startup
        logger.exception("AI provider validation failed unexpectedly")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle hooks."""
    settings: Settings = app.state.settings
    logger.info(
        "Starting %s v%s [%s]",
        settings.app_name,
        settings.app_version,
        settings.app_env,
    )
    ensure_storage_directories(settings)
    init_db(settings)
    await _check_ai_providers(settings)
    logger.info("Application startup complete")
    try:
        yield
    finally:
        logger.info("Shutting down %s", settings.app_name)
        reset_db_state()
        logger.info("Application shutdown complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional settings override (primarily for tests).

    Returns:
        A fully configured ``FastAPI`` instance.
    """
    cfg = settings or get_settings()
    setup_logging(cfg)

    app = FastAPI(
        title=cfg.app_name,
        version=cfg.app_version,
        description=cfg.app_description,
        debug=cfg.debug,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = cfg

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)
    app.include_router(system_router)
    app.include_router(api_v1_router, prefix=cfg.api_v1_prefix)

    return app


app = create_app()
