"""Health check endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

from src.config import settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str


@router.get("/api/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="luxai-api",
        version=settings.app_version,
        environment=settings.environment,
    )
