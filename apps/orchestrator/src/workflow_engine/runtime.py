"""Autonomous workflow execution runtime with recursive planning and reflection."""

import asyncio
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.config import settings
from src.graphs.supervisor import supervisor_graph
from src.state import SupervisorState
from src.telemetry.setup import traced

log = structlog.get_logger(__name__)


class AutonomousRuntime:
    """
    High-level execution runtime that:
    1. Decomposes tasks into sub-goals via the planner
    2. Runs each sub-goal through the supervisor graph
    3. Applies reflection and self-correction
    4. Maintains execution checkpoints
    """

    def __init__(self) -> None:
        self._planner_llm = ChatOpenAI(
            model=settings.default_model,
            temperature=0.2,
            api_key=settings.openai_api_key,
        )
        self._checkpointer = MemorySaver()

    @traced("autonomous_runtime.execute")
    async def execute(
        self,
        task: str,
        agent_id: str,
        session_id: str,
        context: dict[str, Any] | None = None,
        max_iterations: int = 10,
    ) -> dict[str, Any]:
        ctx = context or {}

        # Phase 1: Decompose into sub-goals
        sub_goals = await self._decompose(task, ctx)
        log.info("task_decomposed", session_id=session_id, sub_goals=len(sub_goals))

        # Phase 2: Execute each sub-goal
        results: list[str] = []
        for i, goal in enumerate(sub_goals):
            log.info("executing_sub_goal", session_id=session_id, goal_index=i, goal=goal[:80])
            result = await self._run_sub_goal(
                goal=goal,
                agent_id=agent_id,
                session_id=f"{session_id}:sub-{i}",
                context={**ctx, "previous_results": results},
                max_iterations=max_iterations,
            )
            results.append(result)

        # Phase 3: Reflect and synthesize
        final = await self._synthesize(task, sub_goals, results)

        return {
            "session_id": session_id,
            "task": task,
            "sub_goals": sub_goals,
            "sub_results": results,
            "final_result": final,
            "status": "completed",
        }

    async def _decompose(self, task: str, context: dict[str, Any]) -> list[str]:
        """Break a task into ordered sub-goals using the planner LLM."""
        prompt = f"""Decompose this task into 3-7 concrete, ordered sub-goals.
Return ONLY a numbered list, one goal per line, no other text.

Task: {task}

Context: {context}"""

        response = await self._planner_llm.ainvoke([
            SystemMessage(content="You are a precise task decomposition engine."),
            HumanMessage(content=prompt),
        ])

        lines = str(response.content).strip().split("\n")
        goals = []
        for line in lines:
            line = line.strip()
            if line and line[0].isdigit():
                # Strip leading number + period/dot
                goal = line.split(".", 1)[-1].strip() if "." in line else line[2:].strip()
                if goal:
                    goals.append(goal)

        return goals if goals else [task]

    async def _run_sub_goal(
        self,
        goal: str,
        agent_id: str,
        session_id: str,
        context: dict[str, Any],
        max_iterations: int,
    ) -> str:
        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": max_iterations * 3,
        }

        initial_state: SupervisorState = {
            "messages": [],
            "task": goal,
            "context": context,
            "session_id": session_id,
            "agent_id": agent_id,
            "iteration": 0,
            "max_iterations": max_iterations,
            "next_node": "researcher",
            "final_result": None,
            "error": None,
            "tool_calls_log": [],
            "active_agents": [],
            "agent_outputs": {},
            "plan": [],
            "current_step": 0,
        }

        final_state = await supervisor_graph.ainvoke(initial_state, config=config)  # type: ignore[arg-type]
        return final_state.get("final_result", "") or ""

    async def _synthesize(
        self,
        original_task: str,
        sub_goals: list[str],
        results: list[str],
    ) -> str:
        """Synthesize sub-results into a final coherent answer."""
        synthesis_input = "\n\n".join(
            f"Sub-goal {i + 1}: {goal}\nResult: {result}"
            for i, (goal, result) in enumerate(zip(sub_goals, results))
        )

        prompt = f"""Original task: {original_task}

Sub-goal results:
{synthesis_input}

Synthesize these results into a complete, coherent final answer.
Be concise, structured, and actionable."""

        response = await self._planner_llm.ainvoke([
            SystemMessage(content="You are a synthesis agent. Produce clear, complete answers."),
            HumanMessage(content=prompt),
        ])
        return str(response.content)
