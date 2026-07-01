"""Tests for TradingAgentsAdapter — mocks the TradingAgents debate output."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.trading_agents_adapter import (
    AgentVerdict,
    TradingAgentsAdapter,
    _map_action_to_verdict,
)


# ── _map_action_to_verdict ────────────────────────────────────────────────────

@pytest.mark.parametrize("action,expected", [
    ("BUY", "BULLISH"),
    ("STRONG BUY", "BULLISH"),
    ("BULLISH", "BULLISH"),
    ("SELL", "BEARISH"),
    ("STRONG SELL", "BEARISH"),
    ("BEARISH", "BEARISH"),
    ("HOLD", "NEUTRAL"),
    ("NEUTRAL", "NEUTRAL"),
    ("", "NEUTRAL"),
    ("UNKNOWN_ACTION", "NEUTRAL"),
])
def test_map_action_to_verdict(action: str, expected: str) -> None:
    assert _map_action_to_verdict(action) == expected


# ── AgentVerdict.passes_threshold ────────────────────────────────────────────

def test_passes_threshold_bullish_high_confidence() -> None:
    v = AgentVerdict("NVDA", "BULLISH", 0.80, "strong move", {}, "2024-01-01", 0, 0)
    assert v.passes_threshold(0.65) is True


def test_passes_threshold_neutral_fails_regardless_of_confidence() -> None:
    v = AgentVerdict("NVDA", "NEUTRAL", 0.90, "unclear", {}, "2024-01-01", 0, 0)
    assert v.passes_threshold(0.65) is False


def test_passes_threshold_bearish_low_confidence_fails() -> None:
    v = AgentVerdict("NVDA", "BEARISH", 0.50, "weak", {}, "2024-01-01", 0, 0)
    assert v.passes_threshold(0.65) is False


def test_to_dict_includes_required_fields() -> None:
    v = AgentVerdict("SPY", "BULLISH", 0.72, "reasoning", {"action": "BUY"}, "2024-01-01", 100, 50)
    d = v.to_dict()
    assert d["symbol"] == "SPY"
    assert d["verdict"] == "BULLISH"
    assert d["confidence"] == 0.72
    assert "reasoning" in d


# ── run_debate (mocked TradingAgents) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_debate_success() -> None:
    mock_decision = {"action": "BUY", "confidence": 0.78, "reasoning": "Bullish signals."}
    mock_state = {"total_input_tokens": 3000, "total_output_tokens": 2000}

    mock_graph = MagicMock()
    mock_graph.propagate.return_value = (mock_state, mock_decision)

    adapter = TradingAgentsAdapter(deepseek_api_key="fake-key", anthropic_api_key="fake-ant")

    with patch.dict("sys.modules", {"tradingagents": MagicMock(), "tradingagents.graph": MagicMock(), "tradingagents.graph.trading_graph": MagicMock()}):
        with patch("src.agents.trading_agents_adapter.TradingAgentsAdapter._run_sync") as mock_sync:
            mock_sync.return_value = AgentVerdict(
                "NVDA", "BULLISH", 0.78, "Bullish signals.", mock_decision, "2024-01-01", 3000, 2000
            )
            verdict = await adapter.run_debate("NVDA")

    assert verdict.verdict == "BULLISH"
    assert verdict.confidence == 0.78
    assert verdict.passes_threshold(0.65) is True


@pytest.mark.asyncio
async def test_run_debate_timeout_returns_neutral() -> None:
    import asyncio

    adapter = TradingAgentsAdapter(deepseek_api_key="fake-key", anthropic_api_key="fake-ant")

    async def slow_executor(*args, **kwargs):
        raise TimeoutError()

    with patch.object(adapter, "_run_sync", side_effect=TimeoutError()):
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(side_effect=TimeoutError())
            verdict = await adapter.run_debate("SLOW")

    assert verdict.verdict == "NEUTRAL"
    assert verdict.confidence == 0.0


@pytest.mark.asyncio
async def test_run_debate_exception_returns_neutral() -> None:
    adapter = TradingAgentsAdapter(deepseek_api_key="fake-key", anthropic_api_key="fake-ant")

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = AsyncMock(side_effect=RuntimeError("boom"))
        verdict = await adapter.run_debate("ERR")

    assert verdict.verdict == "NEUTRAL"


# ── log_debate_to_supabase ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_debate_to_supabase_success() -> None:
    verdict = AgentVerdict("TSLA", "BEARISH", 0.71, "Bearish outlook.", {}, "2024-01-01", 100, 50)

    mock_supabase = AsyncMock()
    mock_table = MagicMock()
    mock_insert = MagicMock()
    mock_insert.execute = AsyncMock()
    mock_table.insert = MagicMock(return_value=mock_insert)
    mock_supabase.table = MagicMock(return_value=mock_table)

    adapter = TradingAgentsAdapter(deepseek_api_key="key", anthropic_api_key="ant")
    await adapter.log_debate_to_supabase(verdict, "user-123", mock_supabase)

    mock_supabase.table.assert_called_once_with("scanner_debates")
    mock_table.insert.assert_called_once()


@pytest.mark.asyncio
async def test_log_debate_to_supabase_failure_does_not_raise() -> None:
    """Non-fatal — scanner must continue even if Supabase logging fails."""
    verdict = AgentVerdict("TSLA", "BEARISH", 0.71, "Bearish.", {}, "2024-01-01", 0, 0)

    mock_supabase = AsyncMock()
    mock_supabase.table = MagicMock(side_effect=RuntimeError("db down"))

    adapter = TradingAgentsAdapter(deepseek_api_key="key", anthropic_api_key="ant")
    # Must not raise
    await adapter.log_debate_to_supabase(verdict, "user-123", mock_supabase)
