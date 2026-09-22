"""Tests for paper trading mathematical correctness.

Covers:
  - Long P&L = (current - avg_entry) × qty
  - BUY reduces cash; SELL increases cash
  - Portfolio value = cash + market value of open positions
  - Partial sell: correct realized P&L, correct remaining position
  - Full sell: position removed, full realized P&L
  - Multiple buys → one position per symbol (ALREADY_HOLDING reject)
  - Insufficient cash → order rejected
  - Refresh/live price used for unrealized P&L in portfolio service
  - User isolation via DB persistence
  - Chat room authorization (membership required for messages/portfolio)
  - Stock universe count
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.backtesting.order_execution.broker import SimulatedBroker
from app.backtesting.order_execution.orders import MarketOrder, OrderSide, OrderStatus
from app.backtesting.order_execution.schemas import ExecutionConfig, PositionSizingMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_broker(initial_capital: float = 1_000_000.0) -> SimulatedBroker:
    return SimulatedBroker(
        ExecutionConfig(
            initial_capital=initial_capital,
            position_sizing=PositionSizingMode.FIXED_QUANTITY,
            quantity=1.0,
            slippage_bps=0.0,       # zero slippage — clean accounting
            brokerage_rate=0.0,     # zero brokerage — clean accounting
            brokerage_flat=0.0,
            allow_fractional_shares=True,
        )
    )


def _buy_order(symbol: str, qty: float, price: float) -> MarketOrder:
    return MarketOrder(
        order_id="test-buy",
        symbol=symbol,
        side=OrderSide.BUY,
        quantity=qty,
        reference_price=price,
        submitted_at=datetime.now(timezone.utc),
        strategy_name="test",
        status=OrderStatus.PENDING,
    )


def _sell_order(symbol: str, qty: float, price: float) -> MarketOrder:
    return MarketOrder(
        order_id="test-sell",
        symbol=symbol,
        side=OrderSide.SELL,
        quantity=qty,
        reference_price=price,
        submitted_at=datetime.now(timezone.utc),
        strategy_name="test",
        status=OrderStatus.PENDING,
    )


# ---------------------------------------------------------------------------
# 1. Basic long P&L formula
# ---------------------------------------------------------------------------

class TestLongPnL:
    def test_buy_1_at_150_market_155(self):
        """BUY 1 @ 150, market moves to 155 → unrealized P&L = +5."""
        broker = _make_broker()
        broker.submit_market_order(_buy_order("RELIANCE", 1, 150.0))
        broker.mark_to_market({"RELIANCE": 155.0})
        snap = broker.snapshot()
        assert snap.unrealized_pnl == pytest.approx(5.0)

    def test_buy_10_at_150_market_155(self):
        """BUY 10 @ 150, market moves to 155 → unrealized P&L = +50."""
        broker = _make_broker()
        broker.submit_market_order(_buy_order("RELIANCE", 10, 150.0))
        broker.mark_to_market({"RELIANCE": 155.0})
        snap = broker.snapshot()
        assert snap.unrealized_pnl == pytest.approx(50.0)

    def test_negative_unrealized(self):
        """BUY 1 @ 150, market drops to 140 → unrealized = -10."""
        broker = _make_broker()
        broker.submit_market_order(_buy_order("TCS", 1, 150.0))
        broker.mark_to_market({"TCS": 140.0})
        assert broker.snapshot().unrealized_pnl == pytest.approx(-10.0)


# ---------------------------------------------------------------------------
# 2. Cash accounting
# ---------------------------------------------------------------------------

class TestCashAccounting:
    def test_buy_reduces_cash(self):
        """Cash decreases by notional on BUY."""
        broker = _make_broker(initial_capital=10_000.0)
        broker.submit_market_order(_buy_order("INFY", 5, 1_000.0))
        assert broker.cash == pytest.approx(10_000.0 - 5 * 1_000.0)

    def test_sell_increases_cash(self):
        """Cash increases by notional on SELL."""
        broker = _make_broker(initial_capital=10_000.0)
        broker.submit_market_order(_buy_order("INFY", 5, 1_000.0))
        cash_after_buy = broker.cash
        broker.submit_market_order(_sell_order("INFY", 5, 1_100.0))
        assert broker.cash == pytest.approx(cash_after_buy + 5 * 1_100.0)

    def test_insufficient_cash_rejected(self):
        """Order rejected when cost exceeds available cash."""
        from app.backtesting.order_execution.exceptions import OrderRejectedError
        broker = _make_broker(initial_capital=100.0)
        with pytest.raises(OrderRejectedError):
            broker.submit_market_order(_buy_order("RELIANCE", 10, 500.0))  # costs 5000


# ---------------------------------------------------------------------------
# 3. Portfolio value = cash + market value
# ---------------------------------------------------------------------------

class TestPortfolioValue:
    def test_equity_equals_cash_plus_market_value(self):
        """Equity = cash + qty × current_price (with zero costs)."""
        broker = _make_broker(initial_capital=50_000.0)
        broker.submit_market_order(_buy_order("WIPRO", 10, 400.0))
        broker.mark_to_market({"WIPRO": 450.0})
        snap = broker.snapshot()
        expected_equity = snap.cash + 10 * 450.0
        assert snap.equity == pytest.approx(expected_equity)

    def test_flat_portfolio_equity_equals_cash(self):
        """With no positions, equity = cash."""
        broker = _make_broker(initial_capital=100_000.0)
        snap = broker.snapshot()
        assert snap.equity == pytest.approx(100_000.0)
        assert snap.cash == pytest.approx(100_000.0)


# ---------------------------------------------------------------------------
# 4. Realized P&L
# ---------------------------------------------------------------------------

class TestRealizedPnL:
    def test_full_sell_realized(self):
        """Full sell: realized P&L = (exit - entry) × qty."""
        broker = _make_broker()
        broker.submit_market_order(_buy_order("HDFC", 10, 100.0))
        broker.submit_market_order(_sell_order("HDFC", 10, 120.0))
        snap = broker.snapshot()
        assert snap.realized_pnl == pytest.approx((120.0 - 100.0) * 10)
        assert "HDFC" not in snap.positions or not snap.positions["HDFC"].is_open

    def test_partial_sell_realized_pnl(self):
        """Partial sell realized = (exit - entry) × sold_qty.

        BUY 10 @ 100 → SELL 4 @ 120 → realized = +80, 6 shares remain.
        """
        broker = _make_broker()
        broker.submit_market_order(_buy_order("SBIN", 10, 100.0))
        broker.submit_market_order(_sell_order("SBIN", 4, 120.0))
        snap = broker.snapshot()
        assert snap.realized_pnl == pytest.approx((120.0 - 100.0) * 4)

    def test_partial_sell_remaining_quantity(self):
        """After selling 4 of 10, 6 shares remain."""
        broker = _make_broker()
        broker.submit_market_order(_buy_order("SBIN", 10, 100.0))
        broker.submit_market_order(_sell_order("SBIN", 4, 120.0))
        remaining = broker.get_position("SBIN")
        assert remaining.quantity == pytest.approx(6.0)
        assert remaining.is_open

    def test_partial_sell_average_entry_unchanged(self):
        """Partial sell does not change the average entry price."""
        broker = _make_broker()
        broker.submit_market_order(_buy_order("SBIN", 10, 100.0))
        broker.submit_market_order(_sell_order("SBIN", 3, 130.0))
        pos = broker.get_position("SBIN")
        assert pos.average_entry_price == pytest.approx(100.0)

    def test_partial_sell_cash_increases_correctly(self):
        """Partial sell adds exactly (qty × exec_price) to cash (zero costs)."""
        broker = _make_broker(initial_capital=5_000.0)
        broker.submit_market_order(_buy_order("AXISBANK", 5, 800.0))
        cash_after_buy = broker.cash
        broker.submit_market_order(_sell_order("AXISBANK", 2, 850.0))
        assert broker.cash == pytest.approx(cash_after_buy + 2 * 850.0)

    def test_full_close_after_partial_sell(self):
        """Sell the remaining 6 shares after an earlier partial sell of 4."""
        broker = _make_broker()
        broker.submit_market_order(_buy_order("KOTAKBANK", 10, 100.0))
        broker.submit_market_order(_sell_order("KOTAKBANK", 4, 120.0))
        broker.submit_market_order(_sell_order("KOTAKBANK", 6, 130.0))
        snap = broker.snapshot()
        expected_realized = (120.0 - 100.0) * 4 + (130.0 - 100.0) * 6
        assert snap.realized_pnl == pytest.approx(expected_realized)
        assert "KOTAKBANK" not in snap.positions or not snap.positions["KOTAKBANK"].is_open

    def test_already_holding_buy_rejected(self):
        """Attempting to BUY a symbol already held raises OrderRejectedError."""
        from app.backtesting.order_execution.exceptions import OrderRejectedError
        broker = _make_broker()
        broker.submit_market_order(_buy_order("TATAMOTORS", 5, 200.0))
        with pytest.raises(OrderRejectedError):
            broker.submit_market_order(_buy_order("TATAMOTORS", 5, 210.0))

    def test_sell_more_than_held_rejected(self):
        """Attempting to sell more shares than held raises OrderRejectedError."""
        from app.backtesting.order_execution.exceptions import OrderRejectedError
        broker = _make_broker()
        broker.submit_market_order(_buy_order("NTPC", 5, 150.0))
        with pytest.raises(OrderRejectedError):
            broker.submit_market_order(_sell_order("NTPC", 10, 160.0))


# ---------------------------------------------------------------------------
# 5. Portfolio service — live price used for current_value
# ---------------------------------------------------------------------------

class TestPortfolioService:
    def test_current_value_uses_live_price(self):
        """PortfolioService.kpis() must use the gateway's latest_close,
        not the broker's stale last-price cache."""
        from app.services.dashboard.paper_trading_service import PaperTradingBook
        from app.services.dashboard.portfolio_service import PortfolioService
        from app.backtesting.order_execution.schemas import ExecutionConfig, PositionSizingMode

        book = PaperTradingBook(
            initial_capital=100_000.0,
        )
        # Force a very cheap execution config so we can check exact numbers
        from app.backtesting.order_execution.engine import OrderExecutionEngine
        book.execution = OrderExecutionEngine(
            ExecutionConfig(
                initial_capital=100_000.0,
                position_sizing=PositionSizingMode.FIXED_QUANTITY,
                quantity=10.0,
                slippage_bps=0.0,
                brokerage_rate=0.0,
                allow_fractional_shares=True,
            )
        )

        from app.services.dashboard.schemas import OrderRequest, OrderSide as ApiSide
        result = book.place_order(
            side=ApiSide.BUY,
            request=OrderRequest(symbol="RELIANCE", quantity=10, price=100.0),
            market_price=100.0,
        )
        assert result.accepted, result.message

        # Simulate price moving to 200 (gateway returns it)
        gateway_mock = MagicMock()
        gateway_mock.history_exists.return_value = True

        import pandas as pd
        frame = pd.DataFrame(
            {"date": ["2024-01-01", "2024-01-02"], "close": [100.0, 200.0]}
        )
        frame["date"] = pd.to_datetime(frame["date"])
        gateway_mock.get_history.return_value = frame

        svc = PortfolioService(book)
        kpis = svc.kpis(gateway=gateway_mock)

        # current_value = cash + 10 × 200 = 98_000 + 2_000 = ... wait:
        # cash after buy = 100_000 - 10 × 100 = 99_000; but with the book's
        # execution engine that may size differently. Just assert it's > invested.
        assert kpis.unrealized_pnl == pytest.approx(10 * (200.0 - 100.0))
        assert kpis.current_value == pytest.approx(kpis.available_cash + 10 * 200.0)


# ---------------------------------------------------------------------------
# 6. DB persistence — user isolation
# ---------------------------------------------------------------------------

class TestUserIsolation:
    """Ensures user A's paper trading data is not visible to user B."""

    def test_users_have_separate_books(self, tmp_path: Path):
        """Alice's orders must not appear in Bob's book."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        import app.paper_trading.models  # noqa: F401 register models
        import app.collab.models  # noqa: F401
        import app.market_data.models  # noqa: F401

        engine = create_engine(
            f"sqlite:///{tmp_path / 'test.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        from app.paper_trading.persistence import load_user_book, save_user_book
        from app.services.dashboard.schemas import OrderRequest, OrderSide as ApiSide

        session = Session()

        # Alice places a buy order
        alice_book = load_user_book(session, user_handle="alice")
        from app.backtesting.order_execution.engine import OrderExecutionEngine
        from app.backtesting.order_execution.schemas import ExecutionConfig, PositionSizingMode

        alice_book.execution = OrderExecutionEngine(
            ExecutionConfig(
                initial_capital=1_000_000.0,
                position_sizing=PositionSizingMode.FIXED_QUANTITY,
                quantity=5.0,
                slippage_bps=0.0,
                brokerage_rate=0.0,
                allow_fractional_shares=True,
            )
        )
        result = alice_book.place_order(
            side=ApiSide.BUY,
            request=OrderRequest(symbol="RELIANCE", quantity=5, price=500.0),
            market_price=500.0,
        )
        assert result.accepted
        save_user_book(session, user_handle="alice", book=alice_book)

        # Bob's book should be empty
        bob_book = load_user_book(session, user_handle="bob")
        assert len(bob_book.orders) == 0
        assert bob_book.broker.cash == pytest.approx(1_000_000.0)

        session.close()

    def test_persistence_survives_reload(self, tmp_path: Path):
        """Loading alice's book after saving should restore cash and positions."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        import app.paper_trading.models  # noqa: F401
        import app.collab.models  # noqa: F401
        import app.market_data.models  # noqa: F401

        engine = create_engine(
            f"sqlite:///{tmp_path / 'persist_test.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        from app.paper_trading.persistence import load_user_book, save_user_book
        from app.services.dashboard.schemas import OrderRequest, OrderSide as ApiSide
        from app.backtesting.order_execution.engine import OrderExecutionEngine
        from app.backtesting.order_execution.schemas import ExecutionConfig, PositionSizingMode

        session = Session()
        book = load_user_book(session, user_handle="charlie")
        book.execution = OrderExecutionEngine(
            ExecutionConfig(
                initial_capital=1_000_000.0,
                position_sizing=PositionSizingMode.FIXED_QUANTITY,
                quantity=10.0,
                slippage_bps=0.0,
                brokerage_rate=0.0,
                allow_fractional_shares=True,
            )
        )
        res = book.place_order(
            side=ApiSide.BUY,
            request=OrderRequest(symbol="TCS", quantity=10, price=3000.0),
            market_price=3000.0,
        )
        assert res.accepted
        expected_cash = 1_000_000.0 - 10 * 3000.0
        save_user_book(session, user_handle="charlie", book=book)
        session.close()

        # Reload in a fresh session
        session2 = Session()
        reloaded = load_user_book(session2, user_handle="charlie")
        assert reloaded.broker.cash == pytest.approx(expected_cash)
        pos = reloaded.broker.get_position("TCS")
        assert pos.is_open
        assert pos.quantity == pytest.approx(10.0)
        assert pos.average_entry_price == pytest.approx(3000.0)
        session2.close()


# ---------------------------------------------------------------------------
# 7. Chat room authorization
# ---------------------------------------------------------------------------

class TestChatRoomAuthorization:
    """REST endpoints that require membership must return 403 for non-members."""

    def test_messages_requires_membership(self, client):
        """GET /rooms/{id}/messages as a non-member returns 403."""
        # Create a room
        resp = client.post(
            "/api/v1/collab/rooms",
            json={"name": "test-room", "created_by": "alice"},
        )
        assert resp.status_code == 201
        room_id = resp.json()["data"]["room_id"]

        # Bob is not a member — should get 403
        resp = client.get(
            f"/api/v1/collab/rooms/{room_id}/messages?user=bob"
        )
        assert resp.status_code == 403

    def test_messages_allowed_for_member(self, client):
        """GET /rooms/{id}/messages as a member returns 200."""
        resp = client.post(
            "/api/v1/collab/rooms",
            json={"name": "members-room", "created_by": "alice"},
        )
        room_id = resp.json()["data"]["room_id"]

        # Alice is the creator (and thus a member)
        resp = client.get(
            f"/api/v1/collab/rooms/{room_id}/messages?user=alice"
        )
        assert resp.status_code == 200

    def test_portfolio_requires_membership(self, client):
        """GET /rooms/{id}/portfolio as non-member returns 403."""
        resp = client.post(
            "/api/v1/collab/rooms",
            json={"name": "portfolio-room", "created_by": "alice"},
        )
        room_id = resp.json()["data"]["room_id"]

        resp = client.get(
            f"/api/v1/collab/rooms/{room_id}/portfolio?user=charlie"
        )
        assert resp.status_code == 403

    def test_delete_requires_ownership(self, client):
        """DELETE /rooms/{id} by non-owner returns 403."""
        resp = client.post(
            "/api/v1/collab/rooms",
            json={"name": "owned-room", "created_by": "alice"},
        )
        room_id = resp.json()["data"]["room_id"]

        # Bob tries to delete Alice's room
        resp = client.delete(
            f"/api/v1/collab/rooms/{room_id}?user=bob"
        )
        assert resp.status_code == 403

    def test_delete_allowed_for_owner(self, client):
        """DELETE /rooms/{id} by owner returns 200."""
        resp = client.post(
            "/api/v1/collab/rooms",
            json={"name": "my-room", "created_by": "alice"},
        )
        room_id = resp.json()["data"]["room_id"]

        resp = client.delete(
            f"/api/v1/collab/rooms/{room_id}?user=alice"
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 8. Stock universe count
# ---------------------------------------------------------------------------

class TestStockUniverse:
    def test_universe_count_is_correct(self):
        """Universe service should report the count from the CSV file."""
        from app.services.dashboard.universe_service import UniverseService
        svc = UniverseService()
        count = svc.count()
        # The NIFTY 500 CSV has ~500 EQ-series stocks
        assert count >= 400, f"Expected ≥400 EQ stocks, got {count}"

    def test_list_stocks_respects_limit(self):
        """list_stocks with limit=10 returns at most 10 items."""
        from app.services.dashboard.universe_service import UniverseService
        svc = UniverseService()
        stocks = svc.list_stocks(limit=10)
        assert len(stocks) <= 10

    def test_list_stocks_full_universe(self):
        """list_stocks with limit=501 returns all available stocks."""
        from app.services.dashboard.universe_service import UniverseService
        svc = UniverseService()
        stocks = svc.list_stocks(limit=501)
        total = svc.count()
        assert len(stocks) == total
