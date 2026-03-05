"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from app.models.enums import ErrorCode, MessageType, ResponseType
from app.models.messages import (
    GetHistoryPayload,
    IncomingMessage,
    MessageMetadata,
    OrchestratePayload,
    PingPayload,
    SubscribePayload,
    UserQueryPayload,
)
from app.models.responses import (
    AssistantResponsePayload,
    ErrorPayload,
    HistoryMessage,
    OutgoingResponse,
    ResponseMetadata,
)


class TestMessageMetadata:
    """Tests for MessageMetadata model."""

    def test_valid_metadata(self):
        """Test valid metadata creation."""
        metadata = MessageMetadata(
            session_id="test-session",
            correlation_id="corr-123",
        )
        assert metadata.session_id == "test-session"
        assert metadata.correlation_id == "corr-123"
        assert metadata.timestamp is not None

    def test_metadata_without_correlation_id(self):
        """Test metadata without optional correlation_id."""
        metadata = MessageMetadata(session_id="test-session")
        assert metadata.session_id == "test-session"
        assert metadata.correlation_id is None

    def test_metadata_empty_session_id_fails(self):
        """Test that empty session_id fails validation."""
        with pytest.raises(ValidationError):
            MessageMetadata(session_id="")


class TestUserQueryPayload:
    """Tests for UserQueryPayload model."""

    def test_valid_query(self):
        """Test valid user query."""
        payload = UserQueryPayload(query="What is my balance?")
        assert payload.query == "What is my balance?"
        assert payload.language == "en"

    def test_query_with_context(self):
        """Test query with context."""
        payload = UserQueryPayload(
            query="Help me",
            context={"user_id": "123"},
            language="es",
        )
        assert payload.context == {"user_id": "123"}
        assert payload.language == "es"

    def test_empty_query_fails(self):
        """Test that empty query fails."""
        with pytest.raises(ValidationError):
            UserQueryPayload(query="")

    def test_query_too_long_fails(self):
        """Test that query exceeding max length fails."""
        with pytest.raises(ValidationError):
            UserQueryPayload(query="x" * 4097)


class TestGetHistoryPayload:
    """Tests for GetHistoryPayload model."""

    def test_default_values(self):
        """Test default values."""
        payload = GetHistoryPayload()
        assert payload.limit == 10
        assert payload.offset == 0

    def test_custom_values(self):
        """Test custom values."""
        payload = GetHistoryPayload(limit=50, offset=10)
        assert payload.limit == 50
        assert payload.offset == 10

    def test_limit_bounds(self):
        """Test limit bounds validation."""
        with pytest.raises(ValidationError):
            GetHistoryPayload(limit=0)
        with pytest.raises(ValidationError):
            GetHistoryPayload(limit=101)


class TestOrchestratePayload:
    """Tests for OrchestratePayload model."""

    def test_valid_orchestrate(self):
        """Test valid orchestrate payload."""
        payload = OrchestratePayload(
            action="search",
            parameters={"query": "test"},
            agents=["agent1"],
        )
        assert payload.action == "search"
        assert payload.parameters == {"query": "test"}
        assert payload.agents == ["agent1"]

    def test_empty_action_fails(self):
        """Test that empty action fails."""
        with pytest.raises(ValidationError):
            OrchestratePayload(action="")


class TestIncomingMessage:
    """Tests for IncomingMessage model."""

    def test_valid_message(self):
        """Test valid incoming message."""
        message = IncomingMessage(
            type=MessageType.USER_QUERY,
            payload={"query": "test"},
            metadata=MessageMetadata(session_id="sess-123"),
        )
        assert message.type == "user_query"
        assert message.payload == {"query": "test"}

    def test_invalid_type_fails(self):
        """Test that invalid type fails."""
        with pytest.raises(ValidationError):
            IncomingMessage(
                type="invalid_type",
                payload={},
                metadata=MessageMetadata(session_id="sess-123"),
            )


class TestOutgoingResponse:
    """Tests for OutgoingResponse model."""

    def test_valid_response(self):
        """Test valid outgoing response."""
        response = OutgoingResponse(
            type=ResponseType.ASSISTANT_RESPONSE,
            payload={"message": "Hello"},
            metadata=ResponseMetadata(correlation_id="corr-123"),
        )
        assert response.type == "assistant_response"
        assert response.payload == {"message": "Hello"}

    def test_response_with_latency(self):
        """Test response with latency metadata."""
        response = OutgoingResponse(
            type=ResponseType.PONG,
            payload={},
            metadata=ResponseMetadata(latency_ms=150),
        )
        assert response.metadata.latency_ms == 150


class TestErrorPayload:
    """Tests for ErrorPayload model."""

    def test_valid_error(self):
        """Test valid error payload."""
        error = ErrorPayload(
            code=ErrorCode.INVALID_PAYLOAD,
            message="Invalid payload provided",
            details={"field": "query"},
        )
        assert error.code == ErrorCode.INVALID_PAYLOAD
        assert error.message == "Invalid payload provided"
        assert error.details == {"field": "query"}

    def test_error_without_details(self):
        """Test error without optional details."""
        error = ErrorPayload(
            code=ErrorCode.INTERNAL_ERROR,
            message="Something went wrong",
        )
        assert error.details is None
