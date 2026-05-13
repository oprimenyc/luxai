"""Supervisor graph — orchestrates the research → execute → critique loop."""

from typing import Any, Literal

import structlog
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents import CriticAgent, ExecutorAgent, ResearcherAgent
from src.state import SupervisorState

log = structlog.get_logger(__name__)

_researcher = ResearcherAgent()
_executor = ExecutorAgent()
_critic = CriticAgent()


async def research_node(state: SupervisorState) -> dict[str, Any]:
    return await _researcher.run(dict(state))


async def execute_node(state: SupervisorState) -> dict[str, Any]:
    return await _executor.run(dict(state))


async def critique_node(state: SupervisorState) -> dict[str, Any]:
    return await _critic.run(dict(state))


def route_after_critique(
    state: SupervisorState,
) -> Literal["executor", "__end__"]:
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 25)

    if iteration >= max_iter:
        log.warning("max_iterations_reached", iteration=iteration)
        return END  # type: ignore[return-value]

    next_node = state.get("next_node", "executor")
    if next_node == "END":
        return END  # type: ignore[return-value]
    return "executor"


def build_supervisor_graph() -> CompiledStateGraph:
    graph = StateGraph(SupervisorState)

    graph.add_node("researcher", research_node)
    graph.add_node("executor", execute_node)
    graph.add_node("critic", critique_node)

    graph.set_entry_point("researcher")
    graph.add_edge("researcher", "executor")
    graph.add_edge("executor", "critic")
    graph.add_conditional_edges(
        "critic",
        route_after_critique,
        {"executor": "executor", END: END},
    )

    return graph.compile()


supervisor_graph = build_supervisor_graph()
