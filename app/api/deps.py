"""Shared FastAPI dependencies."""

from fastapi import Request

from app.core.config import Settings


def get_app_settings(request: Request) -> Settings:
    """Return settings bound to the running FastAPI application.

    Using ``app.state.settings`` keeps configuration consistent for the
    process that created the app (including tests that pass overrides).
    """
    return request.app.state.settings
