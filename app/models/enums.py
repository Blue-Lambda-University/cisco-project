"""Enumerations for message types, response types, and error codes."""

from enum import Enum


class MessageType(str, Enum):
    """
    Incoming WebSocket message types.
    
    These represent the different kinds of messages clients can send
    to the mock server.
    """

    USER_QUERY = "user_query"
    PING = "ping"
    GET_HISTORY = "get_history"
    ORCHESTRATE = "orchestrate"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"


class ResponseType(str, Enum):
    """
    Outgoing WebSocket response types.
    
    These represent the different kinds of responses the mock server
    can send back to clients.
    """

    ASSISTANT_RESPONSE = "assistant_response"
    PONG = "pong"
    HISTORY_RESPONSE = "history_response"
    ORCHESTRATION_RESULT = "orchestration_result"
    SUBSCRIPTION_ACK = "subscription_ack"
    ERROR = "error"


class ErrorCode(str, Enum):
    """
    Error codes for error responses.
    
    These provide machine-readable error identification for clients
    to handle errors appropriately.
    """

    UNKNOWN_MESSAGE_TYPE = "UNKNOWN_MESSAGE_TYPE"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    INVALID_JSON = "INVALID_JSON"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    CONNECTION_LIMIT_EXCEEDED = "CONNECTION_LIMIT_EXCEEDED"


class WebSocketSubprotocol(str, Enum):
    """
    Supported WebSocket subprotocols.
    
    Different protocol versions may have different message formats
    or capabilities.
    """

    CIRCUIT_V1 = "circuit.v1"
    CIRCUIT_V2 = "circuit.v2"
