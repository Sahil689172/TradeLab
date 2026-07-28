"""Application-level exception types and FastAPI exception handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.market_data.exceptions import ProviderError, RepositoryError, StorageError
from app.market_data.exceptions import ValidationError as StorageValidationError

logger = logging.getLogger("app.exceptions")


class AppError(Exception):
    """Base application error with an HTTP-facing message and code."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "APP_ERROR",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


def _error_body(
    *,
    code: str,
    message: str,
    details: Any | None = None,
) -> dict[str, Any]:
    """Build a consistent JSON error payload."""
    body: dict[str, Any] = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if details is not None:
        body["error"]["details"] = details
    return body


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """Handle domain/application errors."""
    logger.warning("Application error [%s]: %s", exc.code, exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(code=exc.code, message=exc.message, details=exc.details),
    )


async def http_exception_handler(
    _request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Handle Starlette/FastAPI HTTP exceptions with a uniform body."""
    detail = exc.detail
    message = detail if isinstance(detail, str) else "HTTP error"
    details = detail if not isinstance(detail, str) else None
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(
            code=f"HTTP_{exc.status_code}",
            message=message,
            details=details,
        ),
    )


async def validation_exception_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle Pydantic / request validation errors."""
    logger.info("Validation error: %s", exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_body(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=exc.errors(),
        ),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle unexpected errors without leaking internals to clients."""
    logger.exception(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_body(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred",
        ),
    )


async def storage_exception_handler(
    _request: Request,
    exc: StorageError,
) -> JSONResponse:
    """Map storage/provider errors to stable JSON API responses."""
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "STORAGE_ERROR"
    details = None

    if isinstance(exc, StorageValidationError):
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        code = "MARKET_DATA_VALIDATION_ERROR"
        details = exc.details
    elif isinstance(exc, ProviderError):
        status_code = status.HTTP_502_BAD_GATEWAY
        code = "MARKET_DATA_PROVIDER_ERROR"
    elif isinstance(exc, RepositoryError):
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        code = "MARKET_DATA_REPOSITORY_ERROR"

    logger.warning("Storage error [%s]: %s", code, exc)
    return JSONResponse(
        status_code=status_code,
        content=_error_body(code=code, message=str(exc), details=details),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach global exception handlers to the FastAPI application."""
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StorageError, storage_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
