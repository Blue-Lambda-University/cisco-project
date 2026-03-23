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
) -> tuple[int, dict]:
    """
    Look up connection by requestId, build rich UI response, send to WebSocket.

    Returns (http_status, response_body).

    Idempotency contract:
    - 200 "delivered"          → first successful delivery
    - 200 "already_delivered"  → retry of a previously delivered requestId
    - 200 "connection_closed"  → client disconnected; retrying won't help
    - 200 "unknown_request_id" → requestId not in pending or delivered cache
    - 503 "send_failed"        → connection alive but send failed (transient)
    """
    if correlation_store.was_delivered(request_id):
        logger.info("webhook_already_delivered", request_id=request_id)
        return 200, {"status": "already_delivered"}

    record = correlation_store.get_and_remove(request_id)
    if record is None:
        logger.warning("webhook_request_id_unknown", request_id=request_id)
        return 200, {"status": "unknown_request_id"}

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
        conn_exists = connection_manager.get_connection(record.connection_id) is not None
        if conn_exists:
            # Connection alive but send failed — put the entry back for retry
            correlation_store.set(
                request_id=request_id,
                connection_id=record.connection_id,
                session_id=record.session_id,
                context_id=record.context_id,
                conversation_id=record.conversation_id,
                cp_gutc_id=record.cp_gutc_id,
                referrer=record.referrer,
                query_text=record.query_text,
            )
            logger.warning(
                "webhook_send_failed_transient",
                request_id=request_id,
                connection_id=record.connection_id,
            )
            return 503, {"error": "send_failed"}

        logger.warning(
            "webhook_connection_gone",
            request_id=request_id,
            connection_id=record.connection_id,
        )
        return 200, {"status": "connection_closed"}

    correlation_store.mark_delivered(request_id)
    logger.info(
        "async_response_delivered",
        request_id=request_id,
        connection_id=record.connection_id,
    )
    return 200, {"status": "delivered"}


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

    status_code, body = await _handle_async_response(
        request_id=rid,
        inner=inner,
        correlation_store=correlation_store,
        connection_manager=connection_manager,
        a2a_handler=a2a_handler,
    )
    return JSONResponse(status_code=status_code, content=body)
