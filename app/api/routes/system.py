"""Root and health HTTP endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.engine import Engine

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.db.session import check_database_connection, get_engine
from app.schemas.responses import (
    HealthData,
    HealthResponse,
    RootData,
    RootResponse,
    utc_now,
)

router = APIRouter(tags=["System"])


@router.get(
    "/",
    response_model=RootResponse,
    summary="API root",
    description="Return project metadata and documentation links.",
)
def read_root(settings: Settings = Depends(get_app_settings)) -> RootResponse:
    """Return basic project information and docs URLs."""
    return RootResponse(
        success=True,
        data=RootData(
            name=settings.app_name,
            version=settings.app_version,
            description=settings.app_description,
            documentation={
                "swagger_ui": "/docs",
                "redoc": "/redoc",
                "openapi_json": "/openapi.json",
            },
        ),
        message="Welcome to TradeLab Quant Engine",
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Report application status and database connectivity.",
)
def health_check(
    settings: Settings = Depends(get_app_settings),
    engine: Engine = Depends(get_engine),
) -> HealthResponse:
    """Return liveness details including a live database ping."""
    db_ok = check_database_connection(engine)
    status_value = "healthy" if db_ok else "degraded"
    return HealthResponse(
        success=True,
        data=HealthData(
            status=status_value,
            application=settings.app_name,
            version=settings.app_version,
            environment=settings.app_env,
            database="connected" if db_ok else "disconnected",
            timestamp=utc_now(),
        ),
        message="Health check completed",
    )
