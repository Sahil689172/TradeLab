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
