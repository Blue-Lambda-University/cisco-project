"""WebSocket endpoint for the mock server."""

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.connection_manager import ConnectionManager
from app.dependencies.providers import (
    ConnectionManagerDep,
    MessageHandlerDep,
    SettingsDep,
)
from app.logging.setup import bind_connection_context, clear_context
from app.models.enums import ErrorCode
from app.services.message_handler import MessageHandler

router = APIRouter(tags=["websocket"])

logger = structlog.get_logger()


async def negotiate_subprotocol(
    websocket: WebSocket,
    supported_protocols: list[str],
) -> str | None:
    """
    Negotiate WebSocket subprotocol with the client.
    
    Args:
        websocket: The WebSocket connection.
        supported_protocols: List of supported subprotocols.
        
    Returns:
        The selected subprotocol or None if no match.
    """
    # Get client's requested protocols from headers
    client_protocols_header = websocket.headers.get("sec-websocket-protocol", "")
    client_protocols = [
        p.strip() 
        for p in client_protocols_header.split(",") 
        if p.strip()
    ]
    
    # Find first matching protocol
    for protocol in client_protocols:
        if protocol in supported_protocols:
            return protocol
    
    return None


async def handle_connection(
    websocket: WebSocket,
    connection_manager: ConnectionManager,
    message_handler: MessageHandler,
    subprotocol: str | None,
) -> None:
    """
    Handle a WebSocket connection lifecycle.
    
    Args:
        websocket: The WebSocket connection.
        connection_manager: Connection manager instance.
        message_handler: Message handler instance.
        subprotocol: Negotiated subprotocol.
    """
    # Register connection
    connection_info = await connection_manager.connect(
        websocket=websocket,
        subprotocol=subprotocol,
    )
    
    # Bind connection context for logging
    bind_connection_context(
        connection_id=connection_info.connection_id,
        client_ip=connection_info.client_ip,
        subprotocol=subprotocol,
    )
    
    connection_logger = logger.bind(
        connection_id=connection_info.connection_id,
        client_ip=connection_info.client_ip,
        subprotocol=subprotocol,
    )
    
    try:
        # Message handling loop
        while True:
            # Receive message
            raw_message = await websocket.receive_text()
            
            # Update connection stats
            connection_manager.update_message_count(connection_info.connection_id)
            
            connection_logger.debug(
                "message_received_raw",
                message_length=len(raw_message),
            )
            
            # Handle message
            response = await message_handler.handle_with_context(
                raw_message=raw_message,
                connection_id=connection_info.connection_id,
                subprotocol=subprotocol,
            )
            
            # Send response - both OutgoingResponse and A2AResponse are Pydantic models
            response_json = response.model_dump_json(by_alias=True)
            
            # Log based on response type
            if hasattr(response, 'jsonrpc'):
                # A2A response
                connection_logger.debug(
                    "a2a_response_sent",
                    response_type="a2a",
                )
            else:
                # Standard OutgoingResponse
                connection_logger.debug(
                    "response_sent",
                    response_type=response.type,
                    latency_ms=response.metadata.latency_ms,
                )
            
            await websocket.send_text(response_json)
            
    except WebSocketDisconnect as e:
        connection_logger.info(
            "websocket_disconnected",
            code=e.code,
        )
    except Exception as e:
        connection_logger.exception(
            "websocket_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        # Try to send error response before closing
        try:
            error_response = message_handler._router.create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="Internal server error",
            )
            await websocket.send_text(error_response.model_dump_json())
        except Exception:
            pass  # Connection might be closed
    finally:
        # Clean up
        await connection_manager.disconnect(connection_info.connection_id)
        clear_context()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    settings: SettingsDep,
    connection_manager: ConnectionManagerDep,
    message_handler: MessageHandlerDep,
) -> None:
    """
    Main WebSocket endpoint.
    
    Handles WebSocket connections with:
    - Subprotocol negotiation
    - Connection capacity checking
    - Message handling loop
    - Graceful disconnection
    """
    ws_logger = logger.bind(endpoint="/ws")
    
    # Check capacity before accepting
    if connection_manager.is_at_capacity():
        ws_logger.warning(
            "connection_rejected",
            reason="capacity_exceeded",
            current=connection_manager.active_count,
            max=connection_manager.max_connections,
        )
        await websocket.close(code=1013, reason="Server at capacity")
        return
    
    # Negotiate subprotocol
    subprotocol = await negotiate_subprotocol(
        websocket=websocket,
        supported_protocols=settings.supported_subprotocols,
    )
    
    ws_logger.debug(
        "subprotocol_negotiated",
        selected=subprotocol,
        supported=settings.supported_subprotocols,
    )
    
    # Accept connection with subprotocol
    await websocket.accept(subprotocol=subprotocol)
    
    # Handle connection
    await handle_connection(
        websocket=websocket,
        connection_manager=connection_manager,
        message_handler=message_handler,
        subprotocol=subprotocol,
    )


@router.websocket("/ws/{client_id}")
async def websocket_endpoint_with_client_id(
    websocket: WebSocket,
    client_id: str,
    settings: SettingsDep,
    connection_manager: ConnectionManagerDep,
    message_handler: MessageHandlerDep,
) -> None:
    """
    WebSocket endpoint with client ID in path.
    
    Alternative endpoint that accepts a client identifier in the URL.
    Useful for debugging and testing specific client scenarios.
    """
    ws_logger = logger.bind(endpoint="/ws/{client_id}", client_id=client_id)
    
    # Check capacity
    if connection_manager.is_at_capacity():
        ws_logger.warning(
            "connection_rejected",
            reason="capacity_exceeded",
        )
        await websocket.close(code=1013, reason="Server at capacity")
        return
    
    # Negotiate subprotocol
    subprotocol = await negotiate_subprotocol(
        websocket=websocket,
        supported_protocols=settings.supported_subprotocols,
    )
    
    # Accept connection
    await websocket.accept(subprotocol=subprotocol)
    
    ws_logger.info(
        "client_connected",
        client_id=client_id,
        subprotocol=subprotocol,
    )
    
    # Handle connection
    await handle_connection(
        websocket=websocket,
        connection_manager=connection_manager,
        message_handler=message_handler,
        subprotocol=subprotocol,
    )
