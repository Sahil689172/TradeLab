"""Dashboard REST endpoints for stocks, strategies, portfolio, and paper orders."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_app_settings, get_market_data_gateway
from app.core.config import Settings
from app.market_data.services.market_data_gateway import MarketDataGateway
from app.schemas.responses import SuccessResponse
from app.services.dashboard.favorites_service import get_favorites_service
from app.services.dashboard.market_service import get_market_service
from app.services.dashboard.monte_carlo_service import get_monte_carlo_service
from app.services.dashboard.paper_trading_service import get_paper_book
from app.services.dashboard.portfolio_service import PortfolioService
from app.services.dashboard.schemas import (
    FavoritesResponse,
    MonteCarloDashboardRequest,
    MonteCarloDashboardResponse,
    OHLCVResponse,
    OrderRequest,
    OrderResponse,
    OrderRow,
    OrderSide,
    PortfolioResponse,
    RefreshStatus,
    StockListResponse,
    StockSummary,
    StrategyAnalysisResponse,
    StrategyCatalogItem,
    SystemStatus,
)
from app.services.dashboard.strategy_service import get_strategy_service
from app.services.dashboard.universe_service import get_universe_service

router = APIRouter(tags=["dashboard"])


@router.get("/favorites", response_model=SuccessResponse[FavoritesResponse])
def list_favorites(
    settings: Settings = Depends(get_app_settings),
) -> SuccessResponse[FavoritesResponse]:
    symbols = get_favorites_service(settings).list_symbols()
    return SuccessResponse(data=FavoritesResponse(symbols=symbols))


@router.post("/favorites/{symbol}", response_model=SuccessResponse[FavoritesResponse])
def add_favorite(
    symbol: str,
    settings: Settings = Depends(get_app_settings),
) -> SuccessResponse[FavoritesResponse]:
    symbols = get_favorites_service(settings).add(symbol)
    return SuccessResponse(data=FavoritesResponse(symbols=symbols), message=f"Added {symbol.upper()}")


@router.delete("/favorites/{symbol}", response_model=SuccessResponse[FavoritesResponse])
def remove_favorite(
    symbol: str,
    settings: Settings = Depends(get_app_settings),
) -> SuccessResponse[FavoritesResponse]:
    symbols = get_favorites_service(settings).remove(symbol)
    return SuccessResponse(data=FavoritesResponse(symbols=symbols), message=f"Removed {symbol.upper()}")


@router.get("/stocks", response_model=SuccessResponse[StockListResponse])
def list_stocks(
    q: str = Query(default="", max_length=64),
    limit: int = Query(default=501, ge=1, le=501),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
    settings: Settings = Depends(get_app_settings),
) -> SuccessResponse[StockListResponse]:
    book = get_paper_book()
    favorites = set(get_favorites_service(settings).list_symbols())
    book.favorites = favorites
    holdings = {p.symbol for p in book.broker.snapshot().positions.values() if p.is_open}
    universe = get_universe_service()
    stocks = universe.list_stocks(
        gateway=gateway,
        query=q,
        holdings=holdings,
        watchlist=book.watchlist,
        favorites=favorites,
        limit=limit,
    )
    return SuccessResponse(data=StockListResponse(total=universe.count(), stocks=stocks))


@router.get("/stocks/{symbol}", response_model=SuccessResponse[StockSummary])
def get_stock(
    symbol: str,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
    settings: Settings = Depends(get_app_settings),
) -> SuccessResponse[StockSummary]:
    favorites = set(get_favorites_service(settings).list_symbols())
    stock = get_universe_service().get_stock(symbol, gateway=gateway, favorites=favorites)
    if stock is None:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not in supported universe")
    return SuccessResponse(data=stock)


@router.get("/stocks/{symbol}/ohlcv", response_model=SuccessResponse[OHLCVResponse])
def get_ohlcv(
    symbol: str,
    interval: str = Query(default="1D"),
    limit: int = Query(default=20, ge=1, le=2000),
    before: datetime | None = Query(default=None),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[OHLCVResponse]:
    data = get_market_service().get_ohlcv(
        symbol,
        interval=interval,
        gateway=gateway,
        limit=limit,
        before=before,
    )
    return SuccessResponse(data=data)


@router.post("/market-data/refresh", response_model=SuccessResponse[RefreshStatus])
def refresh_market_data(
    symbol: str | None = Query(default=None),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[RefreshStatus]:
    market = get_market_service()
    if symbol:
        status = market.refresh_symbol(symbol, gateway=gateway)
    else:
        book = get_paper_book()
        holdings = list({p.symbol for p in book.broker.snapshot().positions.values() if p.is_open})
        sample = holdings[:5] if holdings else ["RELIANCE"]
        status = market.refresh_universe_sample(sample, gateway=gateway)
    return SuccessResponse(data=status, message=status.message)


@router.get("/strategies", response_model=SuccessResponse[list[StrategyCatalogItem]])
def list_strategies() -> SuccessResponse[list[StrategyCatalogItem]]:
    return SuccessResponse(data=get_strategy_service().catalog())


@router.get("/strategies/{symbol}/analysis", response_model=SuccessResponse[StrategyAnalysisResponse])
def strategy_analysis(
    symbol: str,
    timeframe: str = Query(default="1D"),
    include_matrix: bool = Query(default=False),
    settings: Settings = Depends(get_app_settings),
) -> SuccessResponse[StrategyAnalysisResponse]:
    analysis = get_strategy_service().analyze(
        symbol,
        timeframe=timeframe,
        storage_dir=str(settings.parquet_storage_dir),
        include_matrix=include_matrix,
    )
    return SuccessResponse(data=analysis)


@router.get("/strategies/{symbol}/timeframes", response_model=SuccessResponse[StrategyAnalysisResponse])
def strategy_timeframes(
    symbol: str,
    settings: Settings = Depends(get_app_settings),
) -> SuccessResponse[StrategyAnalysisResponse]:
    analysis = get_strategy_service().analyze(
        symbol,
        timeframe="1D",
        storage_dir=str(settings.parquet_storage_dir),
        include_matrix=True,
    )
    return SuccessResponse(data=analysis)


@router.post(
    "/stocks/{symbol}/monte-carlo",
    response_model=SuccessResponse[MonteCarloDashboardResponse],
)
def run_monte_carlo(
    symbol: str,
    body: MonteCarloDashboardRequest,
    settings: Settings = Depends(get_app_settings),
) -> SuccessResponse[MonteCarloDashboardResponse]:
    _ = settings
    try:
        result = get_monte_carlo_service().run(symbol, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SuccessResponse(data=result, message=result.message)


@router.get("/portfolio", response_model=SuccessResponse[PortfolioResponse])
def get_portfolio(
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[PortfolioResponse]:
    book = get_paper_book()
    data = PortfolioService(book).build(gateway=gateway)
    return SuccessResponse(data=data)


@router.get("/positions", response_model=SuccessResponse[PortfolioResponse])
def get_positions(
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[PortfolioResponse]:
    return get_portfolio(gateway=gateway)


@router.get("/orders", response_model=SuccessResponse[list[OrderRow]])
def list_orders() -> SuccessResponse[list[OrderRow]]:
    book = get_paper_book()
    from app.services.dashboard.paper_trading_service import _to_order_row

    rows = [_to_order_row(record) for record in book.orders]
    return SuccessResponse(data=rows)


@router.post("/orders/buy", response_model=SuccessResponse[OrderResponse])
def buy_order(
    request: OrderRequest,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[OrderResponse]:
    market = get_market_service()
    price = request.price or market.latest_close(request.symbol, gateway=gateway)
    if price is None or price <= 0:
        raise HTTPException(status_code=400, detail="No market price available; bootstrap symbol or pass price")
    result = get_paper_book().place_order(
        side=OrderSide.BUY,
        request=request,
        market_price=price,
    )
    return SuccessResponse(data=result, message=result.message)


@router.post("/orders/sell", response_model=SuccessResponse[OrderResponse])
def sell_order(
    request: OrderRequest,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[OrderResponse]:
    from app.services.dashboard.schemas import OrderSide as ApiOrderSide

    market = get_market_service()
    price = request.price or market.latest_close(request.symbol, gateway=gateway)
    if price is None or price <= 0:
        raise HTTPException(status_code=400, detail="No market price available; bootstrap symbol or pass price")
    result = get_paper_book().place_order(
        side=ApiOrderSide.SELL,
        request=request,
        market_price=price,
    )
    return SuccessResponse(data=result, message=result.message)


@router.get("/risk", response_model=SuccessResponse[PortfolioResponse])
def get_risk(
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[PortfolioResponse]:
    return get_portfolio(gateway=gateway)


@router.get("/system/status", response_model=SuccessResponse[SystemStatus])
def system_status(
    settings: Settings = Depends(get_app_settings),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[SystemStatus]:
    market = get_market_service()
    return SuccessResponse(
        data=SystemStatus(
            backend_connected=True,
            market_data_source="yfinance",
            yfinance_status="available",
            universe_size=get_universe_service().count(),
            paper_trading=True,
            last_refresh=market.last_refresh,
            environment=settings.app_env,
        ),
    )
