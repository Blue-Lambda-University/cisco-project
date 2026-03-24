"""FastAPI application factory and lifespan management."""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.api import health_router, webhook_router, websocket_router
from app.config import Settings
from app.core.correlation_store import CorrelationStore, RedisCorrelationStore
from app.dependencies.providers import get_connection_manager, get_correlation_store
from app.logging.setup import get_logger, setup_logging


async def _sweep_expired_requests(
    settings: Settings,
) -> None:
    """Background task: periodically remove expired correlation entries and notify the UI."""
    log = get_logger().bind(component="correlation_sweep")
    correlation_store: CorrelationStore | RedisCorrelationStore = get_correlation_store(settings)
    sweep_interval = max(settings.async_response_timeout_seconds // 4, 5)

    while True:
        await asyncio.sleep(sweep_interval)
        try:
            expired = correlation_store.get_expired(settings.async_response_timeout_seconds)
            if not expired:
                continue

            from app.core.connection_manager import ConnectionManager
            cm: ConnectionManager = get_connection_manager(settings)

            for request_id, pending in expired:
                error_payload = json.dumps({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32408,
                        "message": "Request timed out waiting for orchestrator response",
                        "data": {"timeoutSeconds": settings.async_response_timeout_seconds},
                    },
                })
                sent = await cm.send_to_connection(pending.connection_id, error_payload)
                log.warning(
                    "correlation_entry_expired",
                    request_id=request_id,
                    connection_id=pending.connection_id,
                    timeout_seconds=settings.async_response_timeout_seconds,
                    error_delivered=sent,
                )
        except Exception:
            log.exception("correlation_sweep_error")


async def _sweep_idle_connections(settings: Settings) -> None:
    """Background task: periodically close WebSocket connections that have been idle too long."""
    log = get_logger().bind(component="idle_connection_sweep")
    timeout = settings.connection_idle_timeout_seconds
    sweep_interval = max(timeout // 6, 30)

    while True:
        await asyncio.sleep(sweep_interval)
        try:
            from app.core.connection_manager import ConnectionManager
            cm: ConnectionManager = get_connection_manager(settings)
            idle_conns = cm.get_idle_connections(timeout)
            for conn in idle_conns:
                log.info(
                    "closing_idle_connection",
                    connection_id=conn.connection_id,
                    last_message_at=conn.last_message_at.isoformat() if conn.last_message_at else None,
                    idle_timeout_seconds=timeout,
                )
                await cm.close_connection(
                    conn.connection_id,
                    code=1000,
                    reason="Idle timeout",
                )
        except Exception:
            log.exception("idle_connection_sweep_error")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown events for the application.
    """
    logger = get_logger()

    logger.info(
        "application_starting",
        host=app.state.settings.host,
        port=app.state.settings.port,
        environment=app.state.settings.environment,
    )

    sweep_task = asyncio.create_task(
        _sweep_expired_requests(app.state.settings)
    )
    idle_task = asyncio.create_task(
        _sweep_idle_connections(app.state.settings)
    )

    yield

    sweep_task.cancel()
    idle_task.cancel()
    try:
        await sweep_task
    except asyncio.CancelledError:
        pass
    try:
        await idle_task
    except asyncio.CancelledError:
        pass
    logger.info("application_shutting_down")


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Args:
        settings: Optional settings instance. If not provided,
                  settings will be loaded from environment.
    
    Returns:
        Configured FastAPI application.
    """
    if settings is None:
        settings = Settings()
    
    setup_logging(settings)
    
    app = FastAPI(
        title="Uber Assistant WebSocket Server",
        description="WebSocket server for CIRCUIT User Assistant Service",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment == "development" else None,
        redoc_url="/redoc" if settings.environment == "development" else None,
    )
    
    app.state.settings = settings
    
    app.include_router(health_router)
    app.include_router(websocket_router, prefix="/ciscoua/api/v1")
    app.include_router(webhook_router, prefix="/ciscoua/api/v1")
    
    return app


# Create default application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    settings = Settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower(),
    )
