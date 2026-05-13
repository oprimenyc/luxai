"""Workflow execution engine with checkpointing and recovery."""

import asyncio
import time
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import structlog
from supabase import AsyncClient

from src.events.bus import event_bus
from src.events.models import BaseEvent, EventType
from src.workflows.models import (
    StepStatus,
    StepType,
    Workflow,
    WorkflowCreate,
    WorkflowStatus,
    WorkflowStep,
    WorkflowStepExecution,
)

log = structlog.get_logger(__name__)


class WorkflowEngine:
    """
    Executes workflow DAGs with:
    - dependency resolution
    - parallel step execution
    - per-step retry budgets
    - checkpointing after each step
    - recovery from last checkpoint
    """

    def __init__(self, client: AsyncClient) -> None:
        self._client = client
        self._running: dict[str, asyncio.Task] = {}

    async def create(self, user_id: UUID, payload: WorkflowCreate) -> Workflow:
        row = {
            "user_id": str(user_id),
            "name": payload.name,
            "description": payload.description,
            "steps": [s.model_dump() for s in payload.steps],
            "schedule": payload.schedule,
            "context": payload.context,
            "tags": payload.tags,
            "status": WorkflowStatus.DRAFT.value,
        }
        result = await self._client.table("workflows").insert(row).select().single().execute()
        return Workflow(**result.data)

    async def execute(self, workflow_id: UUID, user_id: UUID) -> None:
        wf = await self._get(workflow_id, user_id)
        if not wf:
            raise ValueError(f"Workflow {workflow_id} not found")

        if wf.status not in (WorkflowStatus.DRAFT, WorkflowStatus.FAILED):
            raise ValueError(f"Cannot execute workflow in status {wf.status}")

        task = asyncio.create_task(self._run(wf, user_id))
        self._running[str(workflow_id)] = task
        task.add_done_callback(lambda _: self._running.pop(str(workflow_id), None))

    async def _run(self, wf: Workflow, user_id: UUID) -> None:
        await self._update_status(wf.id, WorkflowStatus.RUNNING, started_at=datetime.utcnow())
        await self._emit(wf, EventType.WORKFLOW_CREATED)

        # Build dependency graph
        step_map = {s.id: s for s in wf.steps}
        completed: set[str] = set()
        step_results: dict[str, Any] = {**wf.context}

        # Resume from checkpoint if available
        if wf.checkpoint:
            completed = set(wf.checkpoint.get("completed_steps", []))
            step_results.update(wf.checkpoint.get("results", {}))
            log.info("workflow_resuming", wf_id=str(wf.id), completed=len(completed))

        try:
            while True:
                # Find steps whose dependencies are satisfied
                ready = [
                    s for s in wf.steps
                    if s.id not in completed
                    and all(dep in completed for dep in s.depends_on)
                ]
                if not ready:
                    break

                # Execute ready steps in parallel
                tasks = [
                    asyncio.create_task(
                        self._execute_step(s, step_results, wf, user_id)
                    )
                    for s in ready
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for step, result in zip(ready, results):
                    if isinstance(result, Exception):
                        if step.on_failure == "fail":
                            raise result
                        log.warning("step_failed_continue", step=step.id, error=str(result))
                    else:
                        completed.add(step.id)
                        if isinstance(result, dict):
                            step_results.update(result)

                    # Checkpoint after each step
                    await self._checkpoint(wf.id, completed, step_results)
                    await self._emit(wf, EventType.WORKFLOW_CHECKPOINT)

            await self._update_status(wf.id, WorkflowStatus.COMPLETED, completed_at=datetime.utcnow())

        except Exception as exc:
            log.error("workflow_failed", wf_id=str(wf.id), error=str(exc))
            await self._update_status(wf.id, WorkflowStatus.FAILED)
            raise

    async def _execute_step(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
        wf: Workflow,
        user_id: UUID,
    ) -> dict[str, Any]:
        await self._emit(wf, EventType.WORKFLOW_STEP_STARTED, step_id=step.id)
        start = time.perf_counter()
        last_error: Exception | None = None

        for attempt in range(step.retry_count + 1):
            try:
                result = await asyncio.wait_for(
                    self._dispatch_step(step, context),
                    timeout=step.timeout_seconds,
                )
                duration_ms = int((time.perf_counter() - start) * 1000)
                await self._emit(
                    wf,
                    EventType.WORKFLOW_STEP_COMPLETED,
                    step_id=step.id,
                    duration_ms=duration_ms,
                )
                return result or {}
            except Exception as exc:
                last_error = exc
                if attempt < step.retry_count:
                    backoff = 2 ** attempt
                    log.warning(
                        "step_retrying",
                        step=step.id,
                        attempt=attempt + 1,
                        backoff=backoff,
                    )
                    await asyncio.sleep(backoff)

        raise last_error or RuntimeError(f"Step {step.id} failed after retries")

    async def _dispatch_step(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if step.type == StepType.AGENT_RUN:
            # Integrate with orchestrator
            import httpx
            from src.config import settings
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{settings.orchestrator_url}/run",
                    json={
                        "task": step.task_template.format(**context),
                        "agent_id": step.agent_id or "default",
                        "session_id": str(uuid4()),
                        "context": context,
                    },
                    timeout=step.timeout_seconds,
                    headers={"X-Orchestrator-Key": settings.orchestrator_api_key},
                )
                resp.raise_for_status()
                return resp.json()

        if step.type == StepType.WAIT:
            duration = step.metadata.get("duration_seconds", 5)
            await asyncio.sleep(duration)
            return {}

        if step.type == StepType.CONDITION:
            expr = step.condition or "True"
            result = eval(expr, {"__builtins__": {}}, context)  # noqa: S307
            return {"condition_result": bool(result)}

        return {}

    async def _get(self, workflow_id: UUID, user_id: UUID) -> Workflow | None:
        result = (
            await self._client.table("workflows")
            .select("*")
            .eq("id", str(workflow_id))
            .eq("user_id", str(user_id))
            .single()
            .execute()
        )
        return Workflow(**result.data) if result.data else None

    async def _update_status(
        self,
        workflow_id: UUID,
        status: WorkflowStatus,
        **kwargs: Any,
    ) -> None:
        data = {"status": status.value, "updated_at": datetime.utcnow().isoformat(), **{
            k: v.isoformat() if isinstance(v, datetime) else v
            for k, v in kwargs.items()
        }}
        await self._client.table("workflows").update(data).eq("id", str(workflow_id)).execute()

    async def _checkpoint(
        self,
        workflow_id: UUID,
        completed: set[str],
        results: dict[str, Any],
    ) -> None:
        checkpoint = {
            "completed_steps": list(completed),
            "results": {k: v for k, v in results.items() if isinstance(v, str | int | float | bool)},
            "checkpointed_at": datetime.utcnow().isoformat(),
        }
        await self._client.table("workflows").update({
            "checkpoint": checkpoint,
        }).eq("id", str(workflow_id)).execute()

    async def _emit(
        self,
        wf: Workflow,
        event_type: EventType,
        **extra: Any,
    ) -> None:
        event = BaseEvent(
            type=event_type,
            user_id=str(wf.user_id),
            payload={"workflow_id": str(wf.id), "workflow_name": wf.name, **extra},
        )
        await event_bus.publish(event)
