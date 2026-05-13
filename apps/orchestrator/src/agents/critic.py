"""Critic agent — evaluates quality of outputs."""

from typing import Any

import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger(__name__)

PASS = "PASS"
FAIL = "FAIL"


class CriticAgent(BaseAgent):
    name = "critic"
    description = "Evaluates the quality and completeness of agent outputs."
    system_prompt = f"""You are a critical evaluation agent. Your role is to:
1. Evaluate the output against the original task requirements.
2. Check for completeness, accuracy, and quality.
3. Identify any gaps, errors, or improvements needed.
4. Return either "{PASS}" or "{FAIL}: <reason>" as your first line.
5. Then provide detailed feedback.

Be strict but fair. Approve only when the output genuinely meets requirements."""

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        task = state.get("task", "")
        result = state.get("final_result", "")
        context = {
            **state.get("context", {}),
            "result_to_evaluate": result,
        }

        log.info("critic_agent_running", task=task[:100])

        evaluation = await self.invoke(
            task=f"Evaluate this output for the task: {task}",
            context=context,
        )

        passed = evaluation.strip().startswith(PASS)
        next_node = "END" if passed else "executor"

        log.info(
            "critic_evaluation_complete",
            passed=passed,
            next_node=next_node,
        )

        return {
            **state,
            "next_node": next_node,
            "iteration": state.get("iteration", 0) + 1,
        }
