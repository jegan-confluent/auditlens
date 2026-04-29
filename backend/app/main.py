import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.routes import admin, events, filters, health, readiness, summary, system
from backend.app.core.config import get_settings
from backend.app.db.database import check_db_health, init_db

logger = logging.getLogger("auditlens.backend")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.api_title, version=settings.api_version)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_slow_queries(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms >= settings.slow_query_ms:
            logger.warning("slow request path=%s elapsed_ms=%.1f", request.url.path, elapsed_ms)
        return response

    @app.exception_handler(Exception)
    async def structured_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled API error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error", "path": request.url.path}},
        )

    @app.on_event("startup")
    def startup() -> None:
        try:
            init_db()
            check_db_health()
        except Exception:
            logger.exception("Database startup check failed; API will continue and report not_ready on /ready")

    app.include_router(health.router)
    app.include_router(readiness.router)
    app.include_router(events.router)
    app.include_router(summary.router)
    app.include_router(filters.router)
    app.include_router(system.router)
    app.include_router(admin.router)
    return app


app = create_app()
