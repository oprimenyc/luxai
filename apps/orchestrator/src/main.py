"""LuxAI Orchestrator — LangGraph FastAPI service."""

import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from src.config import settings
from src.graphs import supervisor_graph
from src.state import SupervisorState

log = structlog.get_logger(__name__)

api_key_header = APIKeyHeader(name="X-Orchestrator-Key", auto_error=False)


def verify_api_key(key: str | None = Security(api_key_header)) -> None:
    if settings.api_key and key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    log.info("orchestrator_starting", environment=settings.environment)
    if settings.langchain_tracing_v2:
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    yield
    log.info("orchestrator_shutting_down")


app = FastAPI(
    title="LuxAI Orchestrator",
    version=settings.app_version,
    docs_url="/docs" if settings.environment != "production" else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=10_000)
    agent_id: str
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    context: dict[str, Any] = Field(default_factory=dict)
    max_iterations: int = Field(default=10, ge=1, le=25)
    model: str = Field(default="gpt-4o")
    stream: bool = False


class RunResponse(BaseModel):
    session_id: str
    result: str
    iterations: int
    status: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "luxai-orchestrator",
        "version": settings.app_version,
    }


@app.post("/run", response_model=RunResponse)
async def run_agent(
    request: RunRequest,
    _: None = Security(verify_api_key),
) -> RunResponse | StreamingResponse:
    initial_state: SupervisorState = {
        "messages": [],
        "task": request.task,
        "context": request.context,
        "session_id": request.session_id,
        "agent_id": request.agent_id,
        "iteration": 0,
        "max_iterations": request.max_iterations,
        "next_node": "researcher",
        "final_result": None,
        "error": None,
        "tool_calls_log": [],
        "active_agents": [],
        "agent_outputs": {},
        "plan": [],
        "current_step": 0,
    }

    if request.stream:
        return _stream_run(initial_state, request.session_id)

    config = {"configurable": {"thread_id": request.session_id}}

    try:
        final_state = await supervisor_graph.ainvoke(initial_state, config=config)  # type: ignore[arg-type]
        return RunResponse(
            session_id=request.session_id,
            result=final_state.get("final_result", ""),
            iterations=final_state.get("iteration", 0),
            status="completed",
        )
    except Exception as exc:
        log.error("graph_run_failed", session_id=request.session_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Orchestration failed: {exc!s}",
        ) from exc


def _stream_run(
    initial_state: SupervisorState,
    session_id: str,
) -> StreamingResponse:
    import json

    async def generator() -> AsyncGenerator[str, None]:
        config = {"configurable": {"thread_id": session_id}}
        async for event in supervisor_graph.astream_events(
            initial_state,  # type: ignore[arg-type]
            config=config,
            version="v2",
        ):
            event_type = event.get("event", "")
            if event_type in {"on_chat_model_stream", "on_chain_end"}:
                data = json.dumps({"event": event_type, "data": str(event.get("data", ""))})
                yield f"data: {data}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.environment == "development",
        log_config=None,
    )
