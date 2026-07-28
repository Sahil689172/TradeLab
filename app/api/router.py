"""API router aggregation."""

from fastapi import APIRouter

from app.api.routes import market, system, v1_root

# Unversioned system routes: /, /health
system_router = APIRouter()
system_router.include_router(system.router)

# Versioned Quant API surface (Phase A2+ modules attach here)
api_v1_router = APIRouter()
api_v1_router.include_router(v1_root.router)
api_v1_router.include_router(market.router)
