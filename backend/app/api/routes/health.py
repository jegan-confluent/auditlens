from fastapi import APIRouter

from backend.app.core.config import get_settings
from backend.app.schemas.response import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", service="auditlens-backend", database_mode=settings.database_mode)
