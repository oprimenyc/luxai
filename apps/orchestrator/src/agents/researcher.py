"""Research agent — gathers and synthesizes information."""

from typing import Any

import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger(__name__)


class ResearcherAgent(BaseAgent):
    name = "researcher"
    description = "Gathers and synthesizes information from available sources."
    system_prompt = """You are an expert research agent. Your role is to:
1. Analyze the given task and identify what information is needed.
2. Formulate precise search queries to gather relevant information.
3. Critically evaluate sources and synthesize findings.
4. Return a structured, comprehensive research summary.

Always cite your reasoning. Be concise but complete. Flag any uncertainty."""

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state.get("task", "")
        context = state.get("context", {})

        log.info("researcher_agent_running", task=task[:100])

        result = await self.invoke(task=task, context=context)

        return {
            **state,
            "synthesized_findings": result,
            "iteration": state.get("iteration", 0) + 1,
        }
