import asyncio
import contextlib
import os
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from backend.app.api.routes import actors, admin, events, filters, feedback as feedback_routes, health, patterns, readiness, summary, system
from backend.app.core.logging import configure_logging
from backend.app.api.routes import settings as settings_routes
from backend.app.api.routes import onboarding as onboarding_routes
from backend.app.api.routes import tableflow as tableflow_routes
from backend.app.api.routes import actor_mappings as actor_mappings_routes
from backend.app.api.routes import resources as resources_routes
from backend.app.core.config import get_settings
from backend.app.core.limiter import limiter
from backend.app.db.database import check_db_health, init_db, SessionLocal
from backend.app.services.event_service import cleanup_retention
from src.product.auth import AuthConfig

configure_logging()
logger = logging.getLogger("auditlens.backend")

_RETENTION_LOOP_STARTUP_DELAY_S = 300   # 5 min after API start
_RETENTION_LOOP_INTERVAL_S = 86400      # 24 h


async def _retention_loop() -> None:
    """Run retention cleanup once daily in the background. Non-fatal."""
    await asyncio.sleep(_RETENTION_LOOP_STARTUP_DELAY_S)
    while True:
        try:
            settings = get_settings()
            if settings.event_retention_days > 0:
                def _run_cleanup():
                    db = SessionLocal()
                    try:
                        return cleanup_retention(
                            db,
                            settings.event_retention_days,
                            raw_payload_retention_days=settings.raw_payload_retention_days,
                            noise_retention_days=settings.noise_retention_days,
                        )
                    finally:
                        db.close()
                result = await asyncio.to_thread(_run_cleanup)
                logger.info("Auto-retention: %s", result)
        except Exception as exc:
            logger.warning("Auto-retention failed (non-fatal): %s", exc)
        await asyncio.sleep(_RETENTION_LOOP_INTERVAL_S)


def _startup_checks() -> None:
    try:
        init_db()
        check_db_health()
    except Exception:
        logger.exception("Database startup check failed; API will continue and report not_ready on /ready")
    if get_settings().api_auth_enabled:
        try:
            AuthConfig.from_env()
        except Exception as exc:
            logger.warning("API auth is enabled but no valid tokens are configured; continuing startup: %s", exc)
    else:
        logger.warning(
            "API_AUTH_ENABLED is false — all endpoints are publicly accessible. "
            "Set API_AUTH_ENABLED=true and configure tokens before any external exposure."
        )
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
    logger.info(
        "AuditLens API started — no telemetry, no phone-home. "
        "All audit data stays within this deployment."
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _startup_checks()
    task = asyncio.create_task(_retention_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


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
    app = FastAPI(title=settings.api_title, version=settings.api_version, lifespan=_lifespan)

    try:
        from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore[import-untyped]
        Instrumentator().instrument(app).expose(app, endpoint="/metrics")
    except ImportError:
        pass

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
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; font-src 'self' data:",
        )
        return response

    @app.exception_handler(Exception)
    async def structured_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled API error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
        )

    app.include_router(health.router)
    app.include_router(readiness.router)
    app.include_router(feedback_routes.router)
    app.include_router(events.router)
    app.include_router(summary.router)
    app.include_router(filters.router)
    app.include_router(system.router)
    app.include_router(admin.router)
    app.include_router(patterns.router)
    app.include_router(actors.router)
    app.include_router(actor_mappings_routes.router)
    app.include_router(resources_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(onboarding_routes.router)
    app.include_router(tableflow_routes.router)
    return app


app = create_app()
