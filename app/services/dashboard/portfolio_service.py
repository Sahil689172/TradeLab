"""Portfolio aggregation from the paper trading book."""

from __future__ import annotations

from app.backtesting.order_execution.schemas import AccountSnapshot
from app.market_data.services.market_data_gateway import MarketDataGateway
from app.services.dashboard.market_service import DashboardMarketService
from app.services.dashboard.paper_trading_service import PaperTradingBook
from app.services.dashboard.schemas import PortfolioKPIs, PortfolioResponse, PositionRow


class PortfolioService:
    def __init__(self, book: PaperTradingBook) -> None:
        self._book = book

    def snapshot(self, account: AccountSnapshot | None = None) -> AccountSnapshot:
        return account or self._book.broker.snapshot()

    def kpis(self, *, gateway: MarketDataGateway | None = None) -> PortfolioKPIs:
        account = self.snapshot()
        market = DashboardMarketService()
        invested = 0.0
        current_value = account.cash
        unrealized = 0.0
        for symbol, position in account.positions.items():
            if not position.is_open:
                continue
            ltp = market.latest_close(symbol, gateway=gateway) if gateway else position.average_entry_price
            ltp = ltp or position.average_entry_price
            inv = position.quantity * position.average_entry_price
            cur = position.quantity * ltp
            invested += inv
            current_value += cur
            unrealized += cur - inv
        total_value = account.equity if account.equity else current_value
        return PortfolioKPIs(
            total_invested=invested,
            current_value=total_value,
            unrealized_pnl=unrealized,
            realized_pnl=account.realized_pnl,
            available_cash=account.cash,
            todays_pnl=0.0,
            initial_capital=self._book.initial_capital,
            exposure_pct=(invested / total_value * 100.0) if total_value else 0.0,
        )

    def build(
        self,
        *,
        gateway: MarketDataGateway | None = None,
    ) -> PortfolioResponse:
        account = self.snapshot()
        market = DashboardMarketService()
        kpis = self.kpis(gateway=gateway)
        rows: list[PositionRow] = []
        per_symbol: dict[str, float] = {}
        for symbol, position in account.positions.items():
            if not position.is_open:
                continue
            ltp = market.latest_close(symbol, gateway=gateway) if gateway else position.average_entry_price
            ltp = ltp or position.average_entry_price
            invested = position.quantity * position.average_entry_price
            current = position.quantity * ltp
            pnl = current - invested
            pnl_pct = (pnl / invested) if invested else 0.0
            per_symbol[symbol] = pnl
            rows.append(
                PositionRow(
                    symbol=symbol,
                    quantity=position.quantity,
                    average_price=position.average_entry_price,
                    ltp=ltp,
                    invested_value=invested,
                    current_value=current,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    stop_loss=position.stop_loss,
                    target=position.target_1,
                    exposure_pct=(current / kpis.current_value * 100.0) if kpis.current_value else 0.0,
                    strategy_name=position.strategy_name,
                ),
            )
        return PortfolioResponse(kpis=kpis, positions=rows, per_symbol_pnl=per_symbol)
