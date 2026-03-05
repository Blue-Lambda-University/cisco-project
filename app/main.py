"""FastAPI application factory and lifespan management."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.api import health_router, webhook_router, websocket_router
from app.config import Settings
from app.logging.setup import get_logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown events for the application.
    """
    logger = get_logger()
    
    # Startup
    logger.info(
        "application_starting",
        host=app.state.settings.host,
        port=app.state.settings.port,
        environment=app.state.settings.environment,
    )
    
    yield
    
    # Shutdown
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
    
    # Setup logging first
    setup_logging(settings)
    
    # Create application
    app = FastAPI(
        title="Mock WebSocket Server",
        description="Mock WebSocket server for CIRCUIT User Assistant Service",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment == "development" else None,
        redoc_url="/redoc" if settings.environment == "development" else None,
    )
    
    # Store settings in app state
    app.state.settings = settings
    
    # Include routers
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
