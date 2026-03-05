"""FastAPI dependency injection providers for application components."""

from functools import lru_cache
from typing import Annotated

import structlog
from fastapi import Depends

from app.config import Settings
from app.core.connection_manager import ConnectionManager
from app.core.latency_simulator import LatencyConfig, LatencySimulator
from app.core.response_router import ResponseRouter
from app.logging.setup import get_logger
from app.services.a2a_handler import A2AHandler, A2AResponseLoader
from app.services.message_handler import MessageHandler
from app.services.response_loader import ResponseLoader


# Singleton instances - initialized lazily
_connection_manager: ConnectionManager | None = None
_response_loader: ResponseLoader | None = None
_a2a_response_loader: A2AResponseLoader | None = None
_latency_simulator: LatencySimulator | None = None
_response_router: ResponseRouter | None = None
_a2a_handler: A2AHandler | None = None


@lru_cache
def get_settings() -> Settings:
    """
    Get cached application settings.
    
    Settings are loaded once and cached for the lifetime of the application.
    This ensures consistent configuration across all components.
    
    Returns:
        Application Settings instance.
    """
    return Settings()


def get_logger_dependency() -> structlog.BoundLogger:
    """
    Provide a bound structlog logger.
    
    Returns:
        A structlog BoundLogger instance.
    """
    return get_logger()


def get_connection_manager(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConnectionManager:
    """
    Get or create the singleton ConnectionManager.
    
    The ConnectionManager is a singleton because it needs to track
    all active WebSocket connections across the application.
    
    Args:
        settings: Application settings.
        
    Returns:
        Singleton ConnectionManager instance.
    """
    global _connection_manager
    
    if _connection_manager is None:
        _connection_manager = ConnectionManager(
            max_connections=settings.max_connections,
        )
    
    return _connection_manager


def get_response_loader(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ResponseLoader:
    """
    Get or create the singleton ResponseLoader.
    
    The ResponseLoader is a singleton to ensure canned responses
    are loaded once and cached for performance.
    
    Args:
        settings: Application settings.
        
    Returns:
        Singleton ResponseLoader instance.
    """
    global _response_loader
    
    if _response_loader is None:
        _response_loader = ResponseLoader(
            responses_path=settings.canned_responses_path,
        )
        # Eagerly load responses
        _response_loader.load()
    
    return _response_loader


def get_latency_simulator(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LatencySimulator:
    """
    Get or create the singleton LatencySimulator.
    
    Args:
        settings: Application settings.
        
    Returns:
        Singleton LatencySimulator instance.
    """
    global _latency_simulator
    
    if _latency_simulator is None:
        config = LatencyConfig(
            enabled=settings.latency_enabled,
            min_ms=settings.latency_min_ms,
            max_ms=settings.latency_max_ms,
            spike_probability=settings.latency_spike_probability,
            spike_min_ms=settings.latency_spike_min_ms,
            spike_max_ms=settings.latency_spike_max_ms,
        )
        _latency_simulator = LatencySimulator(config)
    
    return _latency_simulator


def get_response_router(
    response_loader: Annotated[ResponseLoader, Depends(get_response_loader)],
    latency_simulator: Annotated[LatencySimulator, Depends(get_latency_simulator)],
) -> ResponseRouter:
    """
    Get or create the singleton ResponseRouter.
    
    Args:
        response_loader: Response loader instance.
        latency_simulator: Latency simulator instance.
        
    Returns:
        Singleton ResponseRouter instance.
    """
    global _response_router
    
    if _response_router is None:
        _response_router = ResponseRouter(
            loader=response_loader,
            latency_simulator=latency_simulator,
        )
    
    return _response_router


def get_a2a_response_loader(
    settings: Annotated[Settings, Depends(get_settings)],
) -> A2AResponseLoader:
    """
    Get or create the singleton A2AResponseLoader.
    
    The A2AResponseLoader is a singleton to ensure A2A canned responses
    are loaded once and cached for performance.
    
    Args:
        settings: Application settings.
        
    Returns:
        Singleton A2AResponseLoader instance.
    """
    global _a2a_response_loader
    
    if _a2a_response_loader is None:
        _a2a_response_loader = A2AResponseLoader(
            responses_path=settings.a2a_responses_path,
        )
        # Eagerly load responses
        _a2a_response_loader.load()
    
    return _a2a_response_loader


def get_a2a_handler(
    a2a_response_loader: Annotated[A2AResponseLoader, Depends(get_a2a_response_loader)],
    latency_simulator: Annotated[LatencySimulator, Depends(get_latency_simulator)],
) -> A2AHandler:
    """
    Get or create the singleton A2AHandler.
    
    Args:
        a2a_response_loader: A2A response loader instance.
        latency_simulator: Latency simulator instance.
        
    Returns:
        Singleton A2AHandler instance.
    """
    global _a2a_handler
    
    if _a2a_handler is None:
        _a2a_handler = A2AHandler(
            loader=a2a_response_loader,
            latency_simulator=latency_simulator,
        )
    
    return _a2a_handler


def get_message_handler(
    response_router: Annotated[ResponseRouter, Depends(get_response_router)],
    a2a_handler: Annotated[A2AHandler, Depends(get_a2a_handler)],
    logger: Annotated[structlog.BoundLogger, Depends(get_logger_dependency)],
) -> MessageHandler:
    """
    Create a MessageHandler instance.
    
    MessageHandler is created per-request to allow for request-scoped
    logging context.
    
    Args:
        response_router: Response router instance.
        a2a_handler: A2A handler instance for plain text queries.
        logger: Bound logger instance.
        
    Returns:
        New MessageHandler instance.
    """
    return MessageHandler(
        router=response_router,
        a2a_handler=a2a_handler,
        logger=logger,
    )


# Type aliases for cleaner endpoint signatures
SettingsDep = Annotated[Settings, Depends(get_settings)]
LoggerDep = Annotated[structlog.BoundLogger, Depends(get_logger_dependency)]
ConnectionManagerDep = Annotated[ConnectionManager, Depends(get_connection_manager)]
ResponseLoaderDep = Annotated[ResponseLoader, Depends(get_response_loader)]
A2AResponseLoaderDep = Annotated[A2AResponseLoader, Depends(get_a2a_response_loader)]
LatencySimulatorDep = Annotated[LatencySimulator, Depends(get_latency_simulator)]
ResponseRouterDep = Annotated[ResponseRouter, Depends(get_response_router)]
A2AHandlerDep = Annotated[A2AHandler, Depends(get_a2a_handler)]
MessageHandlerDep = Annotated[MessageHandler, Depends(get_message_handler)]


def reset_singletons() -> None:
    """
    Reset all singleton instances.
    
    Useful for testing to ensure a clean state between tests.
    """
    global _connection_manager, _response_loader, _a2a_response_loader
    global _latency_simulator, _response_router, _a2a_handler
    
    _connection_manager = None
    _response_loader = None
    _a2a_response_loader = None
    _latency_simulator = None
    _response_router = None
    _a2a_handler = None
    
    # Clear the settings cache
    get_settings.cache_clear()
