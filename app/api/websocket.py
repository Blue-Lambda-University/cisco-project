"""WebSocket endpoint with protocol-level keepalive (ws_ping_interval in worker config)."""

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import Settings
from app.core.connection_manager import ConnectionManager
from app.core.rate_limiter import TokenBucket
from app.dependencies.providers import (
    ConnectionManagerDep,
    MessageHandlerDep,
    SettingsDep,
    get_correlation_store,
)
from app.logging.setup import bind_connection_context, clear_context, get_logger
from app.models.enums import ErrorCode
from app.models.responses import UIResponse
from app.services.message_handler import MessageHandler

router = APIRouter(tags=["websocket"])

logger = get_logger()

RATE_LIMIT_ERROR_CODE = -32429


def _build_rate_limit_error(retry_after_ms: int) -> str:
    return json.dumps({
        "jsonrpc": "2.0",
        "id": None,
        "error": {
            "code": RATE_LIMIT_ERROR_CODE,
            "message": "Rate limit exceeded",
            "data": {"retryAfterMs": retry_after_ms},
        },
    })


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
    client_protocols_header = websocket.headers.get("sec-websocket-protocol", "")
    client_protocols = [
        p.strip() 
        for p in client_protocols_header.split(",") 
        if p.strip()
    ]
    
    for protocol in client_protocols:
        if protocol in supported_protocols:
            return protocol
    
    return None


async def handle_connection(
    websocket: WebSocket,
    connection_manager: ConnectionManager,
    message_handler: MessageHandler,
    subprotocol: str | None,
    settings: Settings,
) -> None:
    """
    Handle a WebSocket connection lifecycle.
    
    Args:
        websocket: The WebSocket connection.
        connection_manager: Connection manager instance.
        message_handler: Message handler instance.
        subprotocol: Negotiated subprotocol.
        settings: Application settings (for heartbeat config).
    """
    connection_info = await connection_manager.connect(
        websocket=websocket,
        subprotocol=subprotocol,
    )
    
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

    rate_per_second = settings.rate_limit_messages_per_minute / 60.0
    rate_limiter = TokenBucket(
        rate_per_second=rate_per_second,
        burst_size=settings.rate_limit_burst_size,
    )

    try:
        while True:
            raw_message = await websocket.receive_text()

            # Rate limit check
            allowed, wait_seconds = rate_limiter.consume()
            if not allowed:
                retry_after_ms = int(wait_seconds * 1000)
                connection_logger.warning(
                    "rate_limit_exceeded",
                    retry_after_ms=retry_after_ms,
                )
                await websocket.send_text(_build_rate_limit_error(retry_after_ms))
                continue
            
            connection_manager.update_message_count(connection_info.connection_id)
            
            connection_logger.debug(
                "message_received_raw",
                message_length=len(raw_message),
            )
            
            response = await message_handler.handle_with_context(
                raw_message=raw_message,
                connection_id=connection_info.connection_id,
                subprotocol=subprotocol,
                send_fn=websocket.send_text,
            )
            
            if response is None:
                connection_logger.debug("a2a_response_deferred", response_type="async_forwarded")
                continue

            response_json = response.model_dump_json(by_alias=True)

            if isinstance(response, UIResponse):
                connection_logger.debug("a2a_response_sent", response_type="ui_response")
            elif hasattr(response, "jsonrpc") and hasattr(response, "error"):
                connection_logger.debug("a2a_response_sent", response_type="a2a_error")
            elif hasattr(response, "type"):
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
        try:
            error_response = message_handler._router.create_error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="Internal server error",
            )
            await websocket.send_text(error_response.model_dump_json())
        except Exception:
            pass
    finally:
        correlation_store = get_correlation_store()
        orphaned = await correlation_store.remove_by_connection(connection_info.connection_id)
        if orphaned:
            connection_logger.info(
                "orphaned_correlation_entries_removed",
                request_ids=orphaned,
            )
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
    - Server-side heartbeat (ping/pong)
    - Message handling loop
    - Graceful disconnection
    """
    ws_logger = logger.bind(endpoint="/ciscoua/api/v1/ws")
    
    if connection_manager.is_at_capacity():
        ws_logger.warning(
            "connection_rejected",
            reason="capacity_exceeded",
            current=connection_manager.active_count,
            max=connection_manager.max_connections,
        )
        await websocket.close(code=1013, reason="Server at capacity")
        return
    
    subprotocol = await negotiate_subprotocol(
        websocket=websocket,
        supported_protocols=settings.supported_subprotocols,
    )
    
    ws_logger.debug(
        "subprotocol_negotiated",
        selected=subprotocol,
        supported=settings.supported_subprotocols,
    )
    
    await websocket.accept(subprotocol=subprotocol)
    
    await handle_connection(
        websocket=websocket,
        connection_manager=connection_manager,
        message_handler=message_handler,
        subprotocol=subprotocol,
        settings=settings,
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
    ws_logger = logger.bind(endpoint="/ciscoua/api/v1/ws/{client_id}", client_id=client_id)
    
    if connection_manager.is_at_capacity():
        ws_logger.warning(
            "connection_rejected",
            reason="capacity_exceeded",
        )
        await websocket.close(code=1013, reason="Server at capacity")
        return
    
    subprotocol = await negotiate_subprotocol(
        websocket=websocket,
        supported_protocols=settings.supported_subprotocols,
    )
    
    await websocket.accept(subprotocol=subprotocol)
    
    ws_logger.info(
        "client_connected",
        client_id=client_id,
        subprotocol=subprotocol,
    )
    
    await handle_connection(
        websocket=websocket,
        connection_manager=connection_manager,
        message_handler=message_handler,
        subprotocol=subprotocol,
        settings=settings,
    )
