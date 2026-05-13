"""Session management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from src.middleware.auth import AuthenticatedUser, get_current_user
from src.models.session import Session, SessionCreate
from src.services import SessionService, get_supabase_client

router = APIRouter(prefix="/sessions", tags=["sessions"])


async def get_session_service() -> SessionService:
    client = await get_supabase_client()
    return SessionService(client)


@router.get("", response_model=list[Session])
async def list_sessions(
    agent_id: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: SessionService = Depends(get_session_service),
) -> list[Session]:
    sessions_data, _ = await service.list_sessions(
        user_id=current_user.user_id,
        agent_id=agent_id,
        page=page,
        page_size=page_size,
    )
    return [Session(**s) for s in sessions_data]


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: SessionService = Depends(get_session_service),
) -> Session:
    data = payload.model_dump()
    data["user_id"] = str(current_user.user_id)
    data["agent_id"] = str(payload.agent_id)
    result = await service.create_session(data)
    return Session(**result)


@router.get("/{session_id}", response_model=Session)
async def get_session(
    session_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: SessionService = Depends(get_session_service),
) -> Session:
    result = await service.get_session(
        session_id=session_id,
        user_id=current_user.user_id,
    )
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return Session(**result)


@router.get("/{session_id}/stream")
async def stream_session(
    session_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: SessionService = Depends(get_session_service),
) -> StreamingResponse:
    session = await service.get_session(
        session_id=session_id,
        user_id=current_user.user_id,
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    async def event_generator():  # type: ignore[return]
        yield f"data: {{'session_id': '{session_id}', 'status': 'connected'}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
