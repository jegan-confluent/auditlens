from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.schemas.response import FilterOptionsResponse
from backend.app.services.filter_options_service import get_filter_options
from backend.app.api.routes.patterns import _require_viewer

router = APIRouter(tags=["filters"])


@router.get("/filters/options", response_model=FilterOptionsResponse)
def filters_options(db: Session = Depends(get_db), _auth: None = Depends(_require_viewer)) -> dict[str, list[str]]:
    return get_filter_options(db)
