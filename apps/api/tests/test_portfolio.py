"""Unit tests for PortfolioManager fill accounting."""

from __future__ import annotations

import pytest

from src.trading.models import Fill, OrderSide
from src.trading.portfolio import PortfolioManager


@pytest.fixture
def pm() -> PortfolioManager:
    from src.trading.models import ExecutionMode
    return PortfolioManager("test", initial_cash=10_000.0, execution_mode=ExecutionMode.PAPER)


def _fill(
    symbol: str = "AAPL",
    side: OrderSide = OrderSide.BUY,
    qty: int = 10,
    price: float = 100.0,
    commission: float = 0.0,
) -> Fill:
    from uuid import uuid4
    return Fill(
        order_id=uuid4(),
        broker_order_id=str(uuid4()),
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        commission=commission,
    )


# ── Buy / open long ───────────────────────────────────────────────────────────


class TestOpenLong:
    async def test_cash_reduced(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0))
        snap = await pm.snapshot()
        assert snap.cash == pytest.approx(10_000.0 - 1_000.0)

    async def test_position_created(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0))
        snap = await pm.snapshot()
        assert "AAPL" in snap.positions
        pos = snap.positions["AAPL"]
        assert pos.qty == 10
        assert pos.avg_cost == pytest.approx(100.0)

    async def test_commission_subtracted(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0, commission=5.0))
        snap = await pm.snapshot()
        assert snap.cash == pytest.approx(10_000.0 - 1_000.0 - 5.0)


# ── Sell / close long ─────────────────────────────────────────────────────────


class TestCloseLong:
    async def test_position_removed_on_full_close(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0))
        await pm.apply_fill(_fill(side=OrderSide.SELL, qty=10, price=110.0))
        snap = await pm.snapshot()
        assert "AAPL" not in snap.positions

    async def test_pnl_correct(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0))
        pnl = await pm.apply_fill(_fill(side=OrderSide.SELL, qty=10, price=110.0))
        assert pnl is not None
        assert pnl.realized_pnl == pytest.approx(100.0)  # 10 * (110 - 100)

    async def test_partial_close_leaves_position(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0))
        await pm.apply_fill(_fill(side=OrderSide.SELL, qty=5, price=110.0))
        snap = await pm.snapshot()
        assert snap.positions["AAPL"].qty == 5

    async def test_realized_pnl_accumulates(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0))
        await pm.apply_fill(_fill(side=OrderSide.SELL, qty=10, price=110.0))
        snap = await pm.snapshot()
        assert snap.realized_pnl == pytest.approx(100.0)

    async def test_loss_recorded(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0))
        pnl = await pm.apply_fill(_fill(side=OrderSide.SELL, qty=10, price=90.0))
        assert pnl is not None
        assert pnl.realized_pnl == pytest.approx(-100.0)  # 10 * (90 - 100)

    async def test_commission_reduces_pnl(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0))
        pnl = await pm.apply_fill(_fill(side=OrderSide.SELL, qty=10, price=110.0, commission=5.0))
        assert pnl is not None
        assert pnl.realized_pnl == pytest.approx(95.0)


# ── Weighted average cost ─────────────────────────────────────────────────────


class TestWeightedAverageCost:
    async def test_average_cost_updates_on_add(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0))  # avg = 100
        await pm.apply_fill(_fill(qty=10, price=120.0))  # avg = 110
        snap = await pm.snapshot()
        assert snap.positions["AAPL"].qty == 20
        assert snap.positions["AAPL"].avg_cost == pytest.approx(110.0)


# ── Mark-to-market ────────────────────────────────────────────────────────────


class TestMarkToMarket:
    async def test_updates_current_price(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0))
        await pm.mark_to_market({"AAPL": 115.0})
        snap = await pm.snapshot()
        assert snap.positions["AAPL"].current_price == pytest.approx(115.0)
        assert snap.unrealized_pnl == pytest.approx(150.0)  # 10 * (115 - 100)

    async def test_ignores_unknown_symbols(self, pm: PortfolioManager) -> None:
        await pm.mark_to_market({"TSLA": 200.0})  # no TSLA position — should not raise
        snap = await pm.snapshot()
        assert snap.equity == pytest.approx(10_000.0)


# ── Equity calculation ────────────────────────────────────────────────────────


class TestEquity:
    async def test_equity_equals_cash_plus_market_value(self, pm: PortfolioManager) -> None:
        await pm.apply_fill(_fill(qty=10, price=100.0))  # cash = $9k
        await pm.mark_to_market({"AAPL": 110.0})         # market value = $1,100
        snap = await pm.snapshot()
        assert snap.equity == pytest.approx(9_000.0 + 1_100.0)
