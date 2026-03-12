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
from app.models.webhook_requests import WebhookIncomingBody
from app.services.a2a_handler import A2AHandler

router = APIRouter(prefix="/ws", tags=["webhooks"])
logger = get_logger()


def get_correlation_store_dep() -> CorrelationStore | RedisCorrelationStore:
    """Return the singleton correlation store."""
    return get_correlation_store()


async def _handle_async_response(
    request_id: str,
    body: WebhookIncomingBody,
    correlation_store: CorrelationStore | RedisCorrelationStore,
    connection_manager: ConnectionManager,
    a2a_handler: A2AHandler,
) -> tuple[bool, str]:
    """
    Look up connection by requestId, build A2A response, send to WebSocket.
    Returns (success, error_message).
    """
    record = correlation_store.get_and_remove(request_id)
    if record is None:
        return False, "requestId not found or already consumed"

    session_id = body.session_id or record.session_id
    context_id = body.context_id or record.context_id
    conversation_id = record.conversation_id
    content = body.content or "(No content)"
    cp_gutc_id = body.cp_gutc_id or record.cp_gutc_id
    referrer = body.referrer or record.referrer
    query_text = record.query_text

    ui_response = a2a_handler.build_a2a_response_from_content(
        text_content=content,
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
    correlation_store: Annotated[CorrelationStore | RedisCorrelationStore, Depends(get_correlation_store)],
    connection_manager: ConnectionManagerDep,
    a2a_handler: Annotated[A2AHandler, Depends(get_a2a_handler)],
) -> JSONResponse:
    """
    Receive async response from the orchestrator.
    The requestId in the body is used to look up the correlation store.
    ACK with 200 so the orchestrator can consider the message delivered.
    Return 5xx on failure so the orchestrator can retry.
    """
    rid = body.request_id
    if not rid:
        logger.warning("webhook_async_response_missing_request_id")
        return JSONResponse(
            status_code=400,
            content={"error": "requestId required in body"},
        )

    success, err = await _handle_async_response(
        request_id=rid,
        body=body,
        correlation_store=correlation_store,
        connection_manager=connection_manager,
        a2a_handler=a2a_handler,
    )
    if success:
        return JSONResponse(status_code=200, content={"status": "delivered"})
    return JSONResponse(status_code=503, content={"error": err})
