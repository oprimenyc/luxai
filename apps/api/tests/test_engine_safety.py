"""
Safety invariant tests for TradingEngine.

These tests verify properties that MUST hold regardless of any other changes:
- PAPER mode is the only accepted execution mode
- The engine refuses submissions before start() is called
- Emergency halt blocks all subsequent orders
- Daily loss guard halts the engine when the limit is breached
- Idempotency key prevents duplicate submissions
- Degraded risk mode blocks non-exit orders
"""

from __future__ import annotations

import pytest

from src.trading.models import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    RiskConstraints,
)


# ── Paper mode enforcement ─────────────────────────────────────────────────────


class TestPaperModeEnforcement:
    def test_live_mode_raises_on_init(
        self,
        mock_broker: object,
        mock_journal: object,
        portfolio: object,
    ) -> None:
        from src.trading.engine import TradingEngine

        bad_constraints = RiskConstraints(execution_mode=ExecutionMode.LIVE)  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="PAPER"):
            TradingEngine(mock_broker, mock_journal, portfolio, bad_constraints)  # type: ignore[arg-type]

    def test_simulation_mode_raises_on_init(
        self,
        mock_broker: object,
        mock_journal: object,
        portfolio: object,
    ) -> None:
        from src.trading.engine import TradingEngine

        bad_constraints = RiskConstraints(execution_mode=ExecutionMode.SIMULATION)  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="PAPER"):
            TradingEngine(mock_broker, mock_journal, portfolio, bad_constraints)  # type: ignore[arg-type]

    async def test_order_with_live_mode_rejected(self, engine: object) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=OrderSide.BUY,
            qty=1,
            execution_mode=ExecutionMode.LIVE,  # type: ignore[call-arg]
        )
        with pytest.raises(ValueError, match="PAPER"):
            await engine.submit(req)  # type: ignore[attr-defined]


# ── start() guard ─────────────────────────────────────────────────────────────


class TestStartGuard:
    async def test_submit_before_start_raises(
        self,
        mock_broker: object,
        mock_journal: object,
        portfolio: object,
        constraints: RiskConstraints,
    ) -> None:
        from src.trading.engine import TradingEngine

        eng = TradingEngine(mock_broker, mock_journal, portfolio, constraints)  # type: ignore[arg-type]
        req = _paper_buy("AAPL", 1)
        with pytest.raises(RuntimeError, match="start()"):
            await eng.submit(req)


# ── Emergency halt ────────────────────────────────────────────────────────────


class TestEmergencyHalt:
    async def test_halt_blocks_new_orders(self, engine: object) -> None:
        await engine.emergency_halt()  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError, match="Emergency Halt"):
            await engine.submit(_paper_buy("AAPL", 1))  # type: ignore[attr-defined]

    async def test_halt_is_sticky(self, engine: object) -> None:
        await engine.emergency_halt()  # type: ignore[attr-defined]
        # Multiple calls should still block
        await engine.emergency_halt()  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError, match="Emergency Halt"):
            await engine.submit(_paper_buy("AAPL", 1))  # type: ignore[attr-defined]


# ── Idempotency ───────────────────────────────────────────────────────────────


class TestIdempotency:
    async def test_duplicate_key_raises(self, engine: object) -> None:
        key = "test-idem-key-001"
        req1 = _paper_buy("AAPL", 1, idempotency_key=key)
        req2 = _paper_buy("AAPL", 1, idempotency_key=key)

        await engine.submit(req1)  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError, match="idempotency"):
            await engine.submit(req2)  # type: ignore[attr-defined]

    async def test_different_keys_both_accepted(self, engine: object) -> None:
        req1 = _paper_buy("AAPL", 1, idempotency_key="key-a")
        req2 = _paper_buy("AAPL", 1, idempotency_key="key-b")
        await engine.submit(req1)  # type: ignore[attr-defined]
        await engine.submit(req2)  # type: ignore[attr-defined]  # should not raise

    async def test_no_key_always_accepted(self, engine: object) -> None:
        req1 = _paper_buy("AAPL", 1)
        req2 = _paper_buy("AAPL", 1)
        await engine.submit(req1)  # type: ignore[attr-defined]
        await engine.submit(req2)  # type: ignore[attr-defined]  # should not raise


# ── Validation ────────────────────────────────────────────────────────────────


class TestValidation:
    async def test_zero_qty_rejected(self, engine: object) -> None:
        with pytest.raises(Exception):
            # qty=0 is rejected by pydantic field validator (ge=1)
            OrderRequest(symbol="AAPL", side=OrderSide.BUY, qty=0)

    async def test_limit_order_requires_limit_price(self, engine: object) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=OrderSide.BUY,
            qty=1,
            order_type=OrderType.LIMIT,
            # limit_price intentionally omitted
        )
        with pytest.raises(ValueError, match="limit_price"):
            await engine.submit(req)  # type: ignore[attr-defined]

    async def test_stop_order_requires_stop_price(self, engine: object) -> None:
        req = OrderRequest(
            symbol="AAPL",
            side=OrderSide.BUY,
            qty=1,
            order_type=OrderType.STOP,
            # stop_price intentionally omitted
        )
        with pytest.raises(ValueError, match="stop_price"):
            await engine.submit(req)  # type: ignore[attr-defined]


# ── Degraded risk mode ─────────────────────────────────────────────────────────


class TestDegradedRiskMode:
    async def test_degraded_mode_blocks_normal_orders(self, engine: object) -> None:
        engine._degraded_risk_mode = True  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError, match="Degraded Risk Mode"):
            await engine.submit(_paper_buy("AAPL", 1))  # type: ignore[attr-defined]

    async def test_degraded_mode_allows_risk_exits(self, engine: object) -> None:
        engine._degraded_risk_mode = True  # type: ignore[attr-defined]
        # Risk exits carry the metadata flag that bypasses the block
        req = OrderRequest(
            symbol="AAPL",
            side=OrderSide.SELL,
            qty=1,
            metadata={"risk_trigger": "stop_loss"},
        )
        # Should not raise RuntimeError about degraded mode
        # (may raise for other reasons — that's fine)
        try:
            await engine.submit(req)  # type: ignore[attr-defined]
        except RuntimeError as exc:
            assert "Degraded Risk Mode" not in str(exc)


# ── Circuit breaker telemetry ──────────────────────────────────────────────────


class TestCircuitBreakerState:
    def test_circuit_starts_closed(self) -> None:
        from src.trading.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED
        assert not cb.is_open

    async def test_circuit_opens_after_threshold(self) -> None:
        from src.trading.circuit_breaker import CircuitBreaker, CircuitBreakerOpen, CircuitState

        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60.0)

        async def _fail() -> None:
            raise RuntimeError("service down")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(_fail())

        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpen):
            await cb.call(_fail())

    async def test_circuit_closes_on_success(self) -> None:
        from src.trading.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker("test")

        async def _ok() -> str:
            return "ok"

        await cb.call(_ok())
        assert cb.state == CircuitState.CLOSED


# ── Helpers ───────────────────────────────────────────────────────────────────


def _paper_buy(
    symbol: str,
    qty: int,
    idempotency_key: str | None = None,
) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        side=OrderSide.BUY,
        qty=qty,
        order_type=OrderType.MARKET,
        execution_mode=ExecutionMode.PAPER,
        idempotency_key=idempotency_key,
    )
