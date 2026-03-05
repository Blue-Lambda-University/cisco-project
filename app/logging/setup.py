"""StructLog configuration for structured logging with GCP compatibility."""

import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from app.config import Settings


def add_service_context(
    logger: structlog.BoundLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    Add service-level context to all log entries.
    
    Adds consistent service identification for log aggregation
    and filtering in GCP Cloud Logging.
    """
    event_dict["service"] = "mock-websocket-server"
    event_dict["version"] = "1.0.0"
    return event_dict


def add_gcp_severity(
    logger: structlog.BoundLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    Map structlog levels to GCP Cloud Logging severity levels.
    
    GCP Cloud Logging uses specific severity strings that differ
    from Python's logging levels. This processor ensures logs
    are properly categorized in GCP.
    
    See: https://cloud.google.com/logging/docs/reference/v2/rest/v2/LogEntry#LogSeverity
    """
    level_to_severity = {
        "debug": "DEBUG",
        "info": "INFO",
        "warning": "WARNING",
        "warn": "WARNING",
        "error": "ERROR",
        "critical": "CRITICAL",
        "fatal": "CRITICAL",
        "exception": "ERROR",
    }
    
    level = event_dict.pop("level", "info").lower()
    event_dict["severity"] = level_to_severity.get(level, "DEFAULT")
    
    return event_dict


def add_error_context(
    logger: structlog.BoundLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    Add enhanced error context when exceptions are present.
    
    Extracts exception type and message for easier error analysis.
    """
    exc_info = event_dict.get("exc_info")
    if exc_info:
        if isinstance(exc_info, tuple) and exc_info[0] is not None:
            event_dict["error_type"] = exc_info[0].__name__
            event_dict["error_message"] = str(exc_info[1])
        elif isinstance(exc_info, BaseException):
            event_dict["error_type"] = type(exc_info).__name__
            event_dict["error_message"] = str(exc_info)
    
    return event_dict


def setup_logging(settings: Settings) -> None:
    """
    Configure structlog for the application.
    
    Sets up structured logging with:
    - JSON output for production (GCP Cloud Logging compatible)
    - Pretty console output for development
    - Consistent context binding
    - Exception formatting
    
    Args:
        settings: Application settings for log configuration.
    """
    # Configure standard library logging to work with structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    # Shared processors for both environments
    shared_processors: list[Processor] = [
        # Merge context variables from contextvars
        structlog.contextvars.merge_contextvars,
        # Add log level
        structlog.processors.add_log_level,
        # Add timestamp in ISO format
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # Add service context
        add_service_context,
        # Add error context
        add_error_context,
        # Render stack info
        structlog.processors.StackInfoRenderer(),
        # Decode unicode
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.environment == "production":
        # JSON output for GCP Cloud Logging
        processors: list[Processor] = shared_processors + [
            # Map to GCP severity levels
            add_gcp_severity,
            # Format exception info
            structlog.processors.format_exc_info,
            # Render as JSON
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Pretty console output for development
        processors = shared_processors + [
            # Pretty exceptions
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            ),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger() -> structlog.BoundLogger:
    """
    Get a bound logger instance.
    
    Returns:
        A structlog BoundLogger that can be used for logging.
    """
    return structlog.get_logger()


def bind_connection_context(
    connection_id: str,
    client_ip: str,
    subprotocol: str | None = None,
) -> None:
    """
    Bind connection context to all subsequent logs in this context.
    
    This uses contextvars to ensure the context is properly scoped
    to the current async context (e.g., a WebSocket connection handler).
    
    Args:
        connection_id: Unique identifier for the connection.
        client_ip: Client's IP address.
        subprotocol: Negotiated WebSocket subprotocol.
    """
    structlog.contextvars.bind_contextvars(
        connection_id=connection_id,
        client_ip=client_ip,
        subprotocol=subprotocol,
    )


def bind_message_context(
    message_type: str,
    correlation_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """
    Bind message context for request tracing.
    
    Args:
        message_type: Type of the message being processed.
        correlation_id: Request correlation ID for distributed tracing.
        session_id: Client session identifier.
    """
    structlog.contextvars.bind_contextvars(
        message_type=message_type,
        correlation_id=correlation_id,
        session_id=session_id,
    )


def unbind_message_context() -> None:
    """Unbind message-specific context after processing."""
    structlog.contextvars.unbind_contextvars(
        "message_type",
        "correlation_id",
        "session_id",
    )


def clear_context() -> None:
    """
    Clear all bound context variables.
    
    Should be called when a connection is closed to prevent
    context leakage.
    """
    structlog.contextvars.clear_contextvars()
