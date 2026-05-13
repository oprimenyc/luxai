"""Shared agent state definitions for LangGraph."""

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Core state shared across all agent graph nodes."""

    messages: Annotated[list[AnyMessage], add_messages]
    task: str
    context: dict[str, Any]
    session_id: str
    agent_id: str
    iteration: int
    max_iterations: int
    next_node: str
    final_result: str | None
    error: str | None
    tool_calls_log: list[dict[str, Any]]


class SupervisorState(AgentState):
    """Extended state for the supervisor graph."""

    active_agents: list[str]
    agent_outputs: dict[str, str]
    plan: list[str]
    current_step: int


class ResearchState(AgentState):
    """State for the research sub-graph."""

    search_queries: list[str]
    search_results: list[dict[str, Any]]
    synthesized_findings: str
