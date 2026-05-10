import os
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from backend.app.api.routes import admin, events, filters, health, readiness, summary, system
from backend.app.core.config import get_settings
from backend.app.core.limiter import limiter
from backend.app.db.database import check_db_health, init_db
from src.product.auth import AuthConfig

logger = logging.getLogger("auditlens.backend")

# Routes that must never be rate-limited (kubelet probes, API liveness checks).
_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/live",
        "/ready",
        "/pipeline/ready",
        "/ingestion/ready",
        "/health",
    }
)


def _is_exempt_path(path: str) -> bool:
    return path in _EXEMPT_PATHS


# Wrap the limiter so SlowAPIMiddleware skips probe paths entirely. We patch the
# `limit` callable so the middleware's per-request enforcement returns immediately
# for the exempt set without consuming the bucket.
_original_check = limiter.limit


class _ExemptingMiddleware(SlowAPIMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if _is_exempt_path(request.url.path):
            return await call_next(request)
        return await super().dispatch(request, call_next)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.api_title, version=settings.api_version)

    # Wire slowapi: install the limiter on app state, register the 429 handler,
    # and add the middleware that enforces default_limits across non-exempt
    # routes. Tests that do not exercise rate limiting can flip
    # ``app.state.limiter.enabled = False`` in their fixture.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(_ExemptingMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Actor"],
    )

    @app.middleware("http")
    async def log_slow_queries(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms >= settings.slow_query_ms:
            logger.warning("slow request path=%s elapsed_ms=%.1f", request.url.path, elapsed_ms)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(Exception)
    async def structured_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled API error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
        )

    @app.on_event("startup")
    def startup() -> None:
        try:
            init_db()
            check_db_health()
        except Exception:
            logger.exception("Database startup check failed; API will continue and report not_ready on /ready")
        if os.getenv("API_AUTH_ENABLED", "false").lower() == "true":
            try:
                AuthConfig.from_env()
            except Exception as exc:
                logger.warning("API auth is enabled but no valid tokens are configured; continuing startup: %s", exc)
        # Probe for the noise table once at startup. Absence is non-fatal:
        # /summary/methods, /summary?include_noise, and /events?show_noise
        # all degrade gracefully — but operators benefit from a clear
        # signal that an older deployment is running pre-migration-0007.
        try:
            from sqlalchemy import inspect
            from backend.app.db.database import engine

            if "audit_events_noise" not in set(inspect(engine).get_table_names()):
                logger.warning(
                    "audit_events_noise table not present — /summary/methods and "
                    "/events?show_noise=true will return empty results until Alembic "
                    "migration 0007_noise_table is applied"
                )
            else:
                logger.info("audit_events_noise table present — noise query path active")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("audit_events_noise existence check failed: %s", exc)

    app.include_router(health.router)
    app.include_router(readiness.router)
    app.include_router(events.router)
    app.include_router(summary.router)
    app.include_router(filters.router)
    app.include_router(system.router)
    app.include_router(admin.router)
    return app


app = create_app()
