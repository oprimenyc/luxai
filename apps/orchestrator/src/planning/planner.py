"""Planner agent — decomposes tasks into executable sub-goal sequences."""

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config import settings
from src.telemetry.setup import traced

log = structlog.get_logger(__name__)

PLANNER_SYSTEM_PROMPT = """You are a precision task planner for an enterprise AI OS.

Given a high-level task, decompose it into a sequence of concrete, executable sub-goals.
Each sub-goal must be:
- Atomic and independently executable
- Ordered to respect dependencies
- Actionable by a specialized AI agent
- Between 1-2 sentences in length

Return a numbered list ONLY. No headers, explanations, or commentary.
Example:
1. Search for recent papers on transformer architectures.
2. Extract key findings from each paper.
3. Synthesize findings into a coherent summary.
4. Identify 3 actionable recommendations based on the research."""


class Planner:
    def __init__(self) -> None:
        self._llm = ChatOpenAI(
            model=settings.default_model,
            temperature=0.1,
            api_key=settings.openai_api_key,
            max_tokens=1024,
        )

    @traced("planner.decompose")
    async def decompose(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        max_steps: int = 7,
    ) -> list[str]:
        ctx_str = ""
        if context:
            relevant = {
                k: v for k, v in context.items()
                if isinstance(v, str | int | float | bool) and k not in ("task", "session_id")
            }
            if relevant:
                ctx_str = f"\n\nContext: {relevant}"

        prompt = f"Task: {task}{ctx_str}\n\nMax steps: {max_steps}"

        response = await self._llm.ainvoke([
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])

        steps = self._parse_steps(str(response.content))
        log.info("plan_generated", task_preview=task[:60], steps=len(steps))
        return steps

    @traced("planner.validate")
    async def validate_plan(self, task: str, plan: list[str]) -> tuple[bool, str]:
        """Critic-check a plan for completeness and feasibility."""
        plan_str = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(plan))

        prompt = f"""Evaluate this plan for the given task.

Task: {task}

Plan:
{plan_str}

Answer with one of:
- VALID: <brief reason>
- INVALID: <specific issue>"""

        response = await self._llm.ainvoke([
            SystemMessage(content="You are a rigorous plan validator. Be concise."),
            HumanMessage(content=prompt),
        ])

        content = str(response.content).strip()
        is_valid = content.upper().startswith("VALID")
        return is_valid, content

    @staticmethod
    def _parse_steps(text: str) -> list[str]:
        steps = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Strip numbering (1. / 1) / 1: etc.)
            if line and line[0].isdigit():
                rest = line.lstrip("0123456789").lstrip(".):-").strip()
                if rest:
                    steps.append(rest)
        return steps if steps else [text.strip()]
