"""HTTP webhook endpoints for async orchestrator responses."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.connection_manager import ConnectionManager
from app.core.correlation_store import CorrelationStore, RedisCorrelationStore
from app.dependencies.providers import (
    ConnectionManagerDep,
    get_a2a_handler,
    get_correlation_store,
)
from app.logging.setup import get_logger
from app.models.webhook_requests import WebhookIncomingBody, WebhookIncomingInner
from app.services.a2a_handler import A2AHandler

router = APIRouter(prefix="/ws", tags=["webhooks"])
logger = get_logger()


def get_correlation_store_dep() -> CorrelationStore | RedisCorrelationStore:
    """Return the singleton correlation store."""
    return get_correlation_store()


async def _handle_async_response(
    request_id: str,
    inner: WebhookIncomingInner,
    correlation_store: CorrelationStore | RedisCorrelationStore,
    connection_manager: ConnectionManager,
    a2a_handler: A2AHandler,
) -> tuple[bool, str]:
    """
    Look up connection by requestId, build rich UI response, send to WebSocket.

    Uses non-destructive get() so the entry survives for multiple webhook
    responses that share the same requestId (Scenario B: 1 user msg → N responses).
    Cleanup happens via TTL expiry or WS disconnect.

    Returns (success, error_message).
    """
    record = correlation_store.get(request_id)
    if record is None:
        return False, "requestId not found or expired"

    session_id = inner.session_id or record.session_id
    context_id = inner.context_id or record.context_id
    conversation_id = record.conversation_id
    cp_gutc_id = inner.cp_gutc_id or record.cp_gutc_id
    referrer = inner.referrer or record.referrer
    query_text = record.query_text

    ui_response = a2a_handler.build_a2a_response_from_content(
        content=inner.content,
        session_id=session_id,
        request_id=request_id,
        context_id=context_id,
        conversation_id=conversation_id,
        cp_gutc_id=cp_gutc_id,
        referrer=referrer,
        query_text=query_text,
    )
    response_json = ui_response.model_dump_json(by_alias=True)

    sent = await connection_manager.send_to_connection(record.connection_id, response_json)
    if not sent:
        return False, "connection not found or send failed"

    logger.info(
        "async_response_delivered",
        request_id=request_id,
        connection_id=record.connection_id,
    )
    return True, ""


@router.post("/async/response")
async def webhook_async_response(
    body: WebhookIncomingBody,
    correlation_store: Annotated[CorrelationStore | RedisCorrelationStore, Depends(get_correlation_store_dep)],
    connection_manager: ConnectionManagerDep,
    a2a_handler: Annotated[A2AHandler, Depends(get_a2a_handler)],
) -> JSONResponse:
    """
    Receive async response from the orchestrator.

    Accepts both formats:
      - Wrapped:   {"body": {"requestId": ..., ...}}
      - Unwrapped: {"requestId": ..., ...}

    The requestId is used to look up the correlation store.
    ACK with 200 so the orchestrator can consider the message delivered.
    Return 5xx on failure so the orchestrator can retry.
    """
    inner = body.resolve()
    rid = inner.request_id

    if not rid:
        logger.warning("webhook_async_response_missing_request_id", raw_keys=list(body.model_dump().keys()))
        return JSONResponse(
            status_code=400,
            content={"error": "requestId required in body"},
        )

    logger.info(
        "webhook_async_response_received",
        request_id=rid,
        wrapped=body.body is not None,
        content_type=type(inner.content).__name__,
    )

    success, err = await _handle_async_response(
        request_id=rid,
        inner=inner,
        correlation_store=correlation_store,
        connection_manager=connection_manager,
        a2a_handler=a2a_handler,
    )
    if success:
        return JSONResponse(status_code=200, content={"status": "delivered"})
    return JSONResponse(status_code=503, content={"error": err})
