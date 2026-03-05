"""FastAPI dependency injection providers."""

# Note: Import directly from providers module to avoid circular imports
# Example: from app.dependencies.providers import get_settings

__all__ = [
    # Provider functions
    "get_settings",
    "get_logger_dependency",
    "get_connection_manager",
    "get_response_loader",
    "get_latency_simulator",
    "get_response_router",
    "get_message_handler",
    # Type aliases
    "SettingsDep",
    "LoggerDep",
    "ConnectionManagerDep",
    "ResponseLoaderDep",
    "LatencySimulatorDep",
    "ResponseRouterDep",
    "MessageHandlerDep",
]
