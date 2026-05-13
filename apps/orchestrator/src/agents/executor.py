"""Executor agent — takes action based on research findings."""

from typing import Any

import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger(__name__)


class ExecutorAgent(BaseAgent):
    name = "executor"
    description = "Executes tasks based on a plan and research findings."
    system_prompt = """You are an expert execution agent. Your role is to:
1. Take the research findings and task plan as input.
2. Execute each step methodically and precisely.
3. Handle errors gracefully and adapt when needed.
4. Return a detailed execution report with outcomes.

Be precise, follow the plan, and document every action taken."""

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state.get("task", "")
        findings = state.get("synthesized_findings", "")
        context = {**state.get("context", {}), "research_findings": findings}

        log.info("executor_agent_running", task=task[:100])

        result = await self.invoke(task=task, context=context)

        return {
            **state,
            "final_result": result,
            "iteration": state.get("iteration", 0) + 1,
        }
