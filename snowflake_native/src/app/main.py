"""
POV-4: FastAPI application entry point.

Phase 1 scope: Application bootstrapping and health check only.
No business logic, telemetry, or POV-3 endpoints are registered here.
Future phases will register routers via `app.include_router(...)`.

Reference: docs/hld/high_level_design.md
Reference: docs/lld/low_level_design.md §2
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.core.config import Settings, get_settings
from src.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage application startup and shutdown lifecycle.

    Startup:
        1. Load and validate all settings (fails fast on misconfiguration).
        2. Configure the structured logging framework.
        3. Log application boot confirmation.

    Shutdown:
        1. Log graceful shutdown.
        (Future phases: close Snowflake connections, stop APScheduler, etc.)
    """
    settings: Settings = get_settings()

    # Boot logging first so all subsequent startup logs are structured.
    configure_logging(
        level=settings.logging.level,
        fmt=settings.logging.format,
    )

    logger.info(
        "POV-4 starting up",
        extra={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "environment": settings.environment,
        },
    )

    yield

    logger.info("POV-4 shutting down gracefully.")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """
    Construct and configure the FastAPI application instance.

    Returns:
        A fully configured FastAPI application.
    """
    settings: Settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "POV-4: AI-assisted Query Performance Monitoring & Alerting Agent for Snowflake. "
            "Detects performance bottlenecks, performs LLM-driven root cause analysis, "
            "and emits structured PerformanceFinding payloads for downstream consumption by POV-3."
        ),
        lifespan=lifespan,
        # Disable docs in production to reduce attack surface.
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None if settings.environment == "production" else "/redoc",
    )

    # Future phases will register routers here:
    # application.include_router(findings_router, prefix="/api/v1")

    return application


app: FastAPI = create_app()


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


@app.get(
    "/health",
    tags=["System"],
    summary="Health check",
    description="Returns application liveness status. Used by container orchestrators.",
    response_description="Application health status.",
)
async def health_check() -> JSONResponse:
    """
    Liveness health check endpoint.

    Returns HTTP 200 with a status payload when the application is running.
    No database or Snowflake connectivity is verified here — this is a
    pure liveness probe. Readiness checks will be added in a future phase.
    """
    settings: Settings = get_settings()
    return JSONResponse(
        content={
            "status": "healthy",
            "app": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
        }
    )
