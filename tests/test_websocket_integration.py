"""Integration tests for WebSocket endpoint."""

import json

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_check(self, client: TestClient):
        """Test basic health check."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    def test_liveness_check(self, client: TestClient):
        """Test liveness check."""
        response = client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"

    def test_readiness_check(self, client: TestClient):
        """Test readiness check."""
        response = client.get("/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["checks"]["responses_loaded"] is True

    def test_stats_endpoint(self, client: TestClient):
        """Test stats endpoint."""
        response = client.get("/stats")
        assert response.status_code == 200
        data = response.json()
        assert "connections" in data
        assert "responses" in data


class TestWebSocketConnection:
    """Tests for WebSocket connections."""

    def test_websocket_connect(self, client: TestClient):
        """Test basic WebSocket connection."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            # Connection should be established
            assert websocket is not None

    def test_websocket_with_subprotocol(self, client: TestClient):
        """Test WebSocket connection with subprotocol."""
        with client.websocket_connect(
            "/ciscoua/api/v1/ws",
            subprotocols=["circuit.v1"],
        ) as websocket:
            # Check that subprotocol was accepted
            # Note: TestClient may not fully support subprotocol negotiation
            assert websocket is not None

    def test_websocket_with_cdca2a_subprotocol(self, client: TestClient):
        """Test WebSocket connection with cdca2a subprotocol (Option B)."""
        with client.websocket_connect(
            "/ciscoua/api/v1/ws",
            subprotocols=["cdca2a"],
        ) as websocket:
            assert websocket is not None

    def test_websocket_with_cdca2a_and_token_in_header(self, client: TestClient):
        """Test WebSocket with cdca2a,token-... style header; server selects cdca2."""
        with client.websocket_connect(
            "/ciscoua/api/v1/ws",
            subprotocols=["cdca2a", "token-eyJraWQiOlitUkXPL"],
        ) as websocket:
            assert websocket is not None

    def test_websocket_with_client_id(self, client: TestClient):
        """Test WebSocket connection with client ID path."""
        with client.websocket_connect("/ciscoua/api/v1/ws/test-client-123") as websocket:
            assert websocket is not None


class TestWebSocketMessages:
    """Tests for WebSocket message handling."""

    def test_user_query_message(
        self,
        client: TestClient,
        sample_user_query_message: dict,
    ):
        """Test user query message handling."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json(sample_user_query_message)
            response = websocket.receive_json()
            
            assert response["type"] == "assistant_response"
            assert "message" in response["payload"]
            assert "confidence" in response["payload"]
            assert response["metadata"]["correlation_id"] == "corr-456"
            # Server creates session when none sent
            assert "session_id" in response["metadata"]
            assert response["metadata"]["session_id"] is not None
            assert response["metadata"]["session_id"] and len(response["metadata"]["session_id"]) > 0

    def test_ping_message(
        self,
        client: TestClient,
        sample_ping_message: dict,
    ):
        """Test ping/pong message handling."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json(sample_ping_message)
            response = websocket.receive_json()
            
            assert response["type"] == "pong"
            assert "server_timestamp" in response["payload"]

    def test_get_history_message(
        self,
        client: TestClient,
        sample_get_history_message: dict,
    ):
        """Test get history message handling."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json(sample_get_history_message)
            response = websocket.receive_json()
            
            assert response["type"] == "history_response"
            assert "messages" in response["payload"]
            assert isinstance(response["payload"]["messages"], list)

    def test_orchestrate_message(
        self,
        client: TestClient,
        sample_orchestrate_message: dict,
    ):
        """Test orchestrate message handling."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json(sample_orchestrate_message)
            response = websocket.receive_json()
            
            assert response["type"] == "orchestration_result"
            assert response["payload"]["status"] == "completed"
            assert "agents_invoked" in response["payload"]

    def test_subscribe_message(
        self,
        client: TestClient,
        sample_subscribe_message: dict,
    ):
        """Test subscribe message handling."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json(sample_subscribe_message)
            response = websocket.receive_json()
            
            assert response["type"] == "subscription_ack"
            assert response["payload"]["status"] == "active"

    def test_unknown_message_type(
        self,
        client: TestClient,
        sample_invalid_message: dict,
    ):
        """Test handling of unknown message type."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json(sample_invalid_message)
            response = websocket.receive_json()
            
            assert response["type"] == "error"
            assert response["payload"]["code"] == "VALIDATION_ERROR"

    def test_session_expired_when_unknown_session_id(self, client: TestClient):
        """Test that sending an unknown or expired session_id returns SESSION_EXPIRED."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "type": "user_query",
                "payload": {"query": "Hello", "language": "en"},
                "metadata": {"session_id": "unknown_fake_id_12345"},
            })
            response = websocket.receive_json()
            assert response["type"] == "error"
            assert response["payload"]["code"] == "SESSION_EXPIRED"
            assert "Session expired or not found" in response["payload"]["message"]

    def test_invalid_json(self, client: TestClient):
        """Test handling of invalid JSON."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_text("not valid json {{{")
            response = websocket.receive_json()
            
            assert response["type"] == "error"
            assert response["payload"]["code"] == "INVALID_JSON"

    def test_missing_required_fields(self, client: TestClient):
        """Test handling of message with missing required fields."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            # Missing metadata
            websocket.send_json({
                "type": "ping",
                "payload": {},
            })
            response = websocket.receive_json()
            
            assert response["type"] == "error"
            assert response["payload"]["code"] == "VALIDATION_ERROR"

    def test_invalid_payload_for_type(self, client: TestClient):
        """Test handling of invalid payload for message type."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            # user_query requires 'query' field
            websocket.send_json({
                "type": "user_query",
                "payload": {"wrong_field": "value"},
                "metadata": {"session_id": "test"},
            })
            response = websocket.receive_json()
            
            assert response["type"] == "error"
            assert response["payload"]["code"] == "INVALID_PAYLOAD"


class TestMultipleMessages:
    """Tests for handling multiple messages."""

    def test_multiple_messages_in_sequence(
        self,
        client: TestClient,
        sample_ping_message: dict,
        sample_user_query_message: dict,
    ):
        """Test handling multiple messages in sequence."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            # Send ping
            websocket.send_json(sample_ping_message)
            response1 = websocket.receive_json()
            assert response1["type"] == "pong"
            
            # Send user query
            websocket.send_json(sample_user_query_message)
            response2 = websocket.receive_json()
            assert response2["type"] == "assistant_response"

    def test_correlation_id_preserved(self, client: TestClient):
        """Test that correlation ID is preserved in responses."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            message = {
                "type": "ping",
                "payload": {"client_timestamp": "2024-01-01T00:00:00Z"},
                "metadata": {
                    "session_id": "test",
                    "correlation_id": "unique-corr-id-12345",
                },
            }
            websocket.send_json(message)
            response = websocket.receive_json()
            
            assert response["metadata"]["correlation_id"] == "unique-corr-id-12345"


class TestA2ASendMessage:
    """Tests for A2A agent/sendMessage JSON-RPC request handling."""

    def test_a2a_first_turn(self, client: TestClient):
        """First turn: no sessionId/conversationId; response has sessionId; contextId only if client sent conversationId."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "jsonrpc": "2.0",
                "method": "agent/sendMessage",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "get cases for test@cisco.com"}],
                        "message_id": "msg-001",
                    },
                    "metadata": {"email": "test@cisco.com", "requestId": "req-001"},
                },
                "id": "req-001",
            })
            response = websocket.receive_json()
        assert response.get("jsonrpc") == "2.0"
        assert response.get("id") == "req-001"
        assert "error" not in response
        result = response.get("result", {})
        assert result.get("sessionId") is not None
        assert result["sessionId"] and len(result["sessionId"]) > 0
        # contextId present only when client sent conversationId; server never creates it
        assert "artifacts" in result

    def test_a2a_follow_up(self, client: TestClient):
        """Follow-up: send sessionId and conversationId from first response."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "jsonrpc": "2.0",
                "method": "agent/sendMessage",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "hello"}],
                        "message_id": "msg-1",
                    },
                    "metadata": {"requestId": "req-1"},
                },
                "id": "req-1",
            })
            first = websocket.receive_json()
        assert "error" not in first
        session_id = first["result"]["sessionId"]
        context_id = first["result"]["contextId"]
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "jsonrpc": "2.0",
                "method": "agent/sendMessage",
                "params": {
                    "message": {
                        "role": "user",
                        "context_id": context_id,
                        "parts": [{"kind": "text", "text": "show second case"}],
                        "message_id": "msg-2",
                    },
                    "metadata": {
                        "requestId": "req-2",
                        "sessionId": session_id,
                        "conversationId": context_id,
                    },
                },
                "id": "req-2",
            })
            second = websocket.receive_json()
        assert second.get("id") == "req-2"
        assert "error" not in second
        assert second["result"].get("sessionId") == session_id
        assert second["result"].get("contextId") == context_id

    def test_a2a_session_expired(self, client: TestClient):
        """Unknown/expired sessionId returns A2A error -32000."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "jsonrpc": "2.0",
                "method": "agent/sendMessage",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "hello"}],
                        "message_id": "msg-1",
                    },
                    "metadata": {
                        "sessionId": "unknown_fake_12345",
                        "requestId": "req-1",
                    },
                },
                "id": "req-1",
            })
            response = websocket.receive_json()
        assert response.get("jsonrpc") == "2.0"
        assert response.get("id") == "req-1"
        assert "error" in response
        assert response["error"]["code"] == -32000
        assert "Session expired" in response["error"]["message"]

    def test_a2a_missing_query(self, client: TestClient):
        """Empty or missing query returns A2A error -32602."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "jsonrpc": "2.0",
                "method": "agent/sendMessage",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [],
                        "message_id": "msg-1",
                    },
                    "metadata": {"requestId": "req-1"},
                },
                "id": "req-1",
            })
            response = websocket.receive_json()
        assert response.get("jsonrpc") == "2.0"
        assert "error" in response
        assert response["error"]["code"] == -32602
        assert "query" in response["error"]["message"].lower()
