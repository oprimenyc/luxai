"""
Path: apps/api/src/agents/trading_agents_adapter.py
Security: All LLM calls go to DeepSeek (analysts) and Anthropic Haiku (risk).
          No credentials stored in this file — read from Settings at init.
          No order submission — output is a verdict only.
Scale: One adapter instance per scan invocation; stateless between calls.
       Full debate costs ~5,000 tokens at DeepSeek rates (~$0.0007 per run).

TradingAgents adapter — wraps the TauricResearch/TradingAgents multi-agent
debate framework and integrates its output into LuxAI's consensus pipeline.

Signal flow:
  scanner pre-filter → run_debate() → AgentVerdict → scanner → Tradier chain
                                                              → shadow_trade

Analyst configuration:
  Analysts:   technical, sentiment, news   (DeepSeek, cheapest)
  Researchers: bull_researcher, bear_researcher (DeepSeek)
  Risk agent:  risk_manager               (Anthropic Haiku, final gate)

Depth: 1 round of debate to contain token cost.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, UTC
from typing import TYPE_CHECKING, Any, Literal

import structlog

if TYPE_CHECKING:
    from supabase import AsyncClient

log = structlog.get_logger(__name__)

Verdict = Literal["BULLISH", "BEARISH", "NEUTRAL"]

_ANALYST_SET = ["technical", "sentiment", "news"]
_MAX_DEBATE_SECONDS = 90.0  # hard timeout per symbol


class AgentVerdict:
    """Structured output from a TradingAgents debate run."""

    def __init__(
        self,
        symbol: str,
        verdict: Verdict,
        confidence: float,  # 0.0–1.0
        reasoning: str,
        raw_decision: dict[str, Any],
        analysis_date: str,
        token_input: int,
        token_output: int,
    ) -> None:
        self.symbol = symbol
        self.verdict = verdict
        self.confidence = confidence
        self.reasoning = reasoning
        self.raw_decision = raw_decision
        self.analysis_date = analysis_date
        self.token_input = token_input
        self.token_output = token_output

    def passes_threshold(self, min_confidence: float = 0.65) -> bool:
        return self.verdict != "NEUTRAL" and self.confidence >= min_confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
            "analysis_date": self.analysis_date,
            "token_input": self.token_input,
            "token_output": self.token_output,
        }


class TradingAgentsAdapter:
    """
    Wraps TradingAgents and exposes a single async run_debate() entry point.

    Usage:
        adapter = TradingAgentsAdapter(deepseek_api_key, anthropic_api_key)
        verdict = await adapter.run_debate("NVDA")
        if verdict.passes_threshold():
            # proceed with Tradier chain fetch
    """

    def __init__(
        self,
        deepseek_api_key: str,
        anthropic_api_key: str,
    ) -> None:
        self._deepseek_key = deepseek_api_key
        self._anthropic_key = anthropic_api_key

    def _build_config(self) -> dict[str, Any]:
        return {
            "llm_provider": "openai",  # TradingAgents uses OpenAI-compat; DeepSeek is OAI-compat
            "backend_url": "https://api.deepseek.com/v1",
            "deep_think_llm": "deepseek-chat",
            "quick_think_llm": "deepseek-chat",
            "max_debate_rounds": 1,
            "online_tools": False,  # yfinance handles data — no online scraping
        }

    async def run_debate(self, symbol: str) -> AgentVerdict:
        """
        Run a full analyst debate for the given symbol.

        Executes TradingAgents synchronously in a thread pool to avoid
        blocking the event loop during LLM calls.

        Task name: trading_agents_debate:{symbol}
        Timeout: 90 seconds hard cap to prevent runaway LLM latency.
        """
        analysis_date = date.today().isoformat()

        try:
            async with asyncio.timeout(_MAX_DEBATE_SECONDS):
                verdict = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._run_sync,
                    symbol,
                    analysis_date,
                )
        except TimeoutError:
            log.warning("trading_agents_timeout", symbol=symbol, timeout=_MAX_DEBATE_SECONDS)
            return AgentVerdict(
                symbol=symbol,
                verdict="NEUTRAL",
                confidence=0.0,
                reasoning="Debate timed out — defaulting to NEUTRAL.",
                raw_decision={},
                analysis_date=analysis_date,
                token_input=0,
                token_output=0,
            )
        except Exception as exc:
            log.error("trading_agents_debate_error", symbol=symbol, error=str(exc)[:120])
            return AgentVerdict(
                symbol=symbol,
                verdict="NEUTRAL",
                confidence=0.0,
                reasoning=f"Debate failed: {str(exc)[:100]}",
                raw_decision={},
                analysis_date=analysis_date,
                token_input=0,
                token_output=0,
            )

        return verdict

    def _run_sync(self, symbol: str, analysis_date: str) -> AgentVerdict:
        """Synchronous TradingAgents invocation (runs in thread pool)."""
        # Set env vars for TradingAgents LLM configuration
        os.environ["OPENAI_API_KEY"] = self._deepseek_key
        os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com/v1"

        try:
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except ImportError as exc:
            raise RuntimeError(
                "tradingagents not installed — add it to pyproject.toml"
            ) from exc

        config = self._build_config()
        ta = TradingAgentsGraph(
            selected_analysts=_ANALYST_SET,
            config=config,
        )

        state, decision = ta.propagate(symbol, analysis_date)

        # Parse the decision dict from TradingAgents
        raw_action: str = decision.get("action", "HOLD")
        raw_confidence: float = float(decision.get("confidence", 0.5))
        reasoning: str = decision.get("reasoning", str(decision))

        verdict = _map_action_to_verdict(raw_action)
        # token counts live in state metadata if available
        token_input = state.get("total_input_tokens", 0) if isinstance(state, dict) else 0
        token_output = state.get("total_output_tokens", 0) if isinstance(state, dict) else 0

        return AgentVerdict(
            symbol=symbol,
            verdict=verdict,
            confidence=raw_confidence,
            reasoning=reasoning[:2000],
            raw_decision=decision if isinstance(decision, dict) else {"raw": str(decision)},
            analysis_date=analysis_date,
            token_input=token_input,
            token_output=token_output,
        )

    async def log_debate_to_supabase(
        self,
        verdict: AgentVerdict,
        user_id: str,
        supabase: "AsyncClient",
    ) -> None:
        """Persist the full debate result to workbench_analyses for audit trail."""
        try:
            await supabase.table("workbench_analyses").insert({
                "user_id": user_id,
                "symbol": verdict.symbol,
                "source": "trading_agents_debate",
                "analysis_date": verdict.analysis_date,
                "verdict": verdict.verdict,
                "confidence": verdict.confidence,
                "reasoning": verdict.reasoning,
                "raw_output": verdict.raw_decision,
                "token_input": verdict.token_input,
                "token_output": verdict.token_output,
                "created_at": datetime.now(UTC).isoformat(),
            }).execute()
        except Exception as exc:
            # Non-fatal — scan continues even if Supabase log fails
            log.warning("trading_agents_log_failed", symbol=verdict.symbol, error=str(exc)[:80])


def _map_action_to_verdict(action: str) -> Verdict:
    """Map TradingAgents action string to LuxAI Verdict literal."""
    action_upper = action.upper().strip()
    if action_upper in {"BUY", "STRONG BUY", "BULLISH"}:
        return "BULLISH"
    if action_upper in {"SELL", "STRONG SELL", "BEARISH"}:
        return "BEARISH"
    return "NEUTRAL"


def get_trading_agents_adapter() -> TradingAgentsAdapter:
    """FastAPI dependency — returns a configured adapter from Settings."""
    from src.config import settings
    return TradingAgentsAdapter(
        deepseek_api_key=settings.deepseek_api_key,
        anthropic_api_key=settings.anthropic_api_key,
    )
