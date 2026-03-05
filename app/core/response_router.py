"""Routes incoming messages to appropriate canned responses."""

from datetime import datetime
from typing import Any

import structlog

from app.core.latency_simulator import LatencySimulator
from app.models.enums import ErrorCode, MessageType, ResponseType
from app.models.responses import OutgoingResponse, ResponseMetadata
from app.services.response_loader import ResponseLoader

logger = structlog.get_logger()


class ResponseRouter:
    """
    Routes incoming messages to canned responses.
    
    Handles:
    - Message type to response mapping
    - Template variable substitution
    - Latency simulation
    - Error response generation
    """

    def __init__(
        self,
        loader: ResponseLoader,
        latency_simulator: LatencySimulator,
    ) -> None:
        """
        Initialize the response router.
        
        Args:
            loader: Response loader for canned responses.
            latency_simulator: Latency simulator for delays.
        """
        self._loader = loader
        self._latency_simulator = latency_simulator
        self._logger = logger.bind(component="response_router")

    async def route(
        self,
        message_type: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> OutgoingResponse:
        """
        Route an incoming message to its canned response.
        
        Args:
            message_type: The type of the incoming message.
            payload: The message payload.
            correlation_id: Optional correlation ID for tracing.
            
        Returns:
            The appropriate OutgoingResponse.
        """
        start_time = datetime.utcnow()

        # Get latency override from response config if available
        response_config = self._loader.get_response_config(message_type)
        
        # Simulate latency
        latency_ms = await self._latency_simulator.simulate(message_type)

        # Build template context from payload
        template_context = self._build_template_context(message_type, payload)

        # Get and process the response
        if response_config:
            response_type = response_config.get("type", ResponseType.ERROR.value)
            response_payload = self._process_template(
                response_config.get("payload", {}),
                template_context,
            )
        else:
            # Unknown message type - return error
            self._logger.warning(
                "unknown_message_type",
                message_type=message_type,
            )
            response_type = ResponseType.ERROR.value
            response_payload = {
                "code": ErrorCode.UNKNOWN_MESSAGE_TYPE.value,
                "message": f"Message type '{message_type}' is not recognized",
                "details": {
                    "supported_types": [t.value for t in MessageType],
                },
            }

        # Build metadata
        metadata = ResponseMetadata(
            correlation_id=correlation_id,
            timestamp=datetime.utcnow(),
            latency_ms=latency_ms,
        )

        response = OutgoingResponse(
            type=response_type,
            payload=response_payload,
            metadata=metadata,
        )

        processing_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        self._logger.info(
            "message_routed",
            message_type=message_type,
            response_type=response_type,
            latency_ms=latency_ms,
            processing_time_ms=round(processing_time_ms, 2),
            correlation_id=correlation_id,
        )

        return response

    def create_error_response(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> OutgoingResponse:
        """
        Create an error response.
        
        Args:
            code: Error code.
            message: Human-readable error message.
            details: Additional error details.
            correlation_id: Optional correlation ID.
            
        Returns:
            Error OutgoingResponse.
        """
        return OutgoingResponse(
            type=ResponseType.ERROR.value,
            payload={
                "code": code.value,
                "message": message,
                "details": details,
            },
            metadata=ResponseMetadata(
                correlation_id=correlation_id,
                timestamp=datetime.utcnow(),
            ),
        )

    def _build_template_context(
        self,
        message_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build template context for variable substitution.
        
        Args:
            message_type: The message type.
            payload: The message payload.
            
        Returns:
            Template context dictionary.
        """
        now = datetime.utcnow()
        
        context = {
            # Standard variables
            "timestamp": now.isoformat(),
            "server_timestamp": now.isoformat(),
            "message_type": message_type,
            
            # Time-based variables
            "timestamp_minus_1m": self._time_offset(now, minutes=-1),
            "timestamp_minus_2m": self._time_offset(now, minutes=-2),
            "timestamp_minus_3m": self._time_offset(now, minutes=-3),
            "timestamp_minus_4m": self._time_offset(now, minutes=-4),
            "timestamp_minus_5m": self._time_offset(now, minutes=-5),
        }

        # Add payload fields to context
        for key, value in payload.items():
            context[key] = value
            
            # Create preview for long strings
            if isinstance(value, str) and len(value) > 50:
                context[f"{key}_preview"] = value[:50] + "..."
            elif isinstance(value, str):
                context[f"{key}_preview"] = value

        return context

    def _process_template(
        self,
        template: dict[str, Any] | list | str | Any,
        context: dict[str, Any],
    ) -> Any:
        """
        Recursively process template variables.
        
        Replaces {{variable}} patterns with values from context.
        
        Args:
            template: The template to process.
            context: Variable context.
            
        Returns:
            Processed template with substitutions.
        """
        if isinstance(template, dict):
            return {
                key: self._process_template(value, context)
                for key, value in template.items()
            }
        elif isinstance(template, list):
            return [
                self._process_template(item, context)
                for item in template
            ]
        elif isinstance(template, str):
            return self._substitute_variables(template, context)
        else:
            return template

    def _substitute_variables(
        self,
        text: str,
        context: dict[str, Any],
    ) -> str:
        """
        Substitute {{variable}} patterns in text.
        
        Args:
            text: Text with variables.
            context: Variable context.
            
        Returns:
            Text with substitutions.
        """
        result = text
        
        for key, value in context.items():
            placeholder = f"{{{{{key}}}}}"  # {{key}}
            if placeholder in result:
                if isinstance(value, (list, dict)):
                    # Keep complex types as-is for JSON serialization
                    result = result.replace(placeholder, str(value))
                else:
                    result = result.replace(placeholder, str(value))

        return result

    def _time_offset(self, base: datetime, **kwargs) -> str:
        """
        Calculate a time offset from base time.
        
        Args:
            base: Base datetime.
            **kwargs: timedelta arguments.
            
        Returns:
            ISO formatted datetime string.
        """
        from datetime import timedelta
        return (base + timedelta(**kwargs)).isoformat()
