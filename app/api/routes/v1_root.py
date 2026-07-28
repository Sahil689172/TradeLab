"""Versioned API (v1) routes reserved for Quant Engine modules."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.schemas.responses import SuccessResponse

router = APIRouter(tags=["API v1"])


class ApiVersionData(BaseModel):
    """Metadata for the versioned API root."""

    model_config = ConfigDict(extra="forbid")

    api_version: str = Field(default="v1", description="API version identifier")
    status: str = Field(default="ok", description="API availability status")
    application: str
    app_version: str


@router.get(
    "/",
    response_model=SuccessResponse[ApiVersionData],
    summary="API v1 root",
    description="Confirm the versioned API is available.",
)
def api_v1_root(
    settings: Settings = Depends(get_app_settings),
) -> SuccessResponse[ApiVersionData]:
    """Return versioned API metadata."""
    return SuccessResponse(
        success=True,
        data=ApiVersionData(
            api_version="v1",
            status="ok",
            application=settings.app_name,
            app_version=settings.app_version,
        ),
        message="TradeLab API v1",
    )
