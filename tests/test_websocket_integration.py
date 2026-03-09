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
        """Invalid JSON is treated as plain text and returns a UIResponse."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_text("not valid json {{{")
            response = websocket.receive_json()

            assert response.get("status") == "success"
            assert "response" in response
            assert "a2aResponse" in response

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
        """First turn: no sessionId/conversationId; UIResponse wrapper with a2aResponse inside."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "jsonrpc": "2.0",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "get cases for test@cisco.com"}],
                        "message_id": "msg-001",
                    },
                    "metadata": {"isFirstChat": False},
                },
                "id": "req-001",
            })
            response = websocket.receive_json()
        assert response.get("status") == "success"
        assert "response" in response

        a2a = response.get("a2aResponse", {})
        assert a2a.get("jsonrpc") == "2.0"
        assert a2a.get("id") == "req-001"

        meta = a2a.get("metadata") or {}
        assert meta.get("sessionId") is not None
        assert meta["sessionId"] and len(meta["sessionId"]) > 0

        result = a2a.get("result", {})
        assert "artifacts" in result
        assert result.get("kind") == "task"
        assert result.get("id")
        assert result.get("contextId")
        assert result.get("status", {}).get("state") == "completed"

        # history includes user query
        history = result.get("history", [])
        assert len(history) >= 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "agent"

    def test_a2a_follow_up(self, client: TestClient):
        """Follow-up: send sessionId and conversationId; response matches spec section 5.3."""
        conv_id = "conv-uuid-follow-up-test"
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "jsonrpc": "2.0",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "hello"}],
                    },
                    "metadata": {"isFirstChat": True, "conversationId": conv_id},
                },
                "id": "req-1",
            })
            first = websocket.receive_json()

        # Extract sessionId from welcome (metadata inside result)
        a2a_first = first.get("a2aResponse", {})
        result_first = a2a_first.get("result", {})
        session_id = (result_first.get("metadata") or {}).get("sessionId")
        assert session_id, "first response must include sessionId in a2aResponse.result.metadata"

        # Follow-up request matching spec section 5.2
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "jsonrpc": "2.0",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "get my licensing cases"}],
                    },
                    "metadata": {
                        "sessionId": session_id,
                        "conversationId": conv_id,
                        "CP_GUTC_Id": "gutc-abc123",
                        "referrer": "https://www.cisco.com",
                        "isFirstChat": False,
                    },
                },
                "id": "req-2",
            })
            second = websocket.receive_json()

        # Top-level UIResponse wrapper
        assert second.get("status") == "success"
        assert second.get("error") == {}
        assert second.get("response")
        assert second.get("conversationId") == conv_id
        # contextId is generated (different from conversationId for real A2A)
        assert second.get("contextId")

        # Inner a2aResponse
        a2a = second.get("a2aResponse", {})
        assert a2a.get("id") == "req-2"
        assert a2a.get("jsonrpc") == "2.0"

        # a2aResponse.result matches spec task structure
        result = a2a.get("result", {})
        assert result.get("kind") == "task"
        assert result.get("id")
        assert result.get("contextId")
        assert result.get("status", {}).get("state") == "completed"
        artifacts = result.get("artifacts", [])
        assert len(artifacts) >= 1
        assert artifacts[0].get("name") == "agent_response"

        # history array with user + agent messages
        history = result.get("history", [])
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["kind"] == "message"
        assert "get my licensing cases" in history[0]["parts"][0]["text"]
        assert history[0]["taskId"] == result["id"]
        assert history[1]["role"] == "agent"
        assert history[1]["parts"][0]["text"] == "Processing your request..."

        # metadata at a2aResponse level (not inside result)
        meta = a2a.get("metadata") or {}
        assert meta.get("sessionId") == session_id
        assert meta.get("conversationId") == conv_id
        assert meta.get("CP_GUTC_Id") == "gutc-abc123"
        assert meta.get("referrer") == "https://www.cisco.com"

    def test_a2a_session_expired(self, client: TestClient):
        """Unknown/expired sessionId returns A2A error -32404."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "jsonrpc": "2.0",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "hello"}],
                        "message_id": "msg-1",
                    },
                    "metadata": {
                        "sessionId": "unknown_fake_12345",
                        "isFirstChat": False,
                    },
                },
                "id": "req-1",
            })
            response = websocket.receive_json()
        assert response.get("jsonrpc") == "2.0"
        assert response.get("id") == "req-1"
        assert "error" in response
        assert response["error"]["code"] == -32404
        assert "Session expired" in response["error"]["message"]

    def test_a2a_first_chat_welcome(self, client: TestClient):
        """When isFirstChat is true, return UIResponse with welcome message matching spec format."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "jsonrpc": "2.0",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "Welcome"}],
                    },
                    "metadata": {
                        "sessionId": None,
                        "conversationId": "conv-welcome-test",
                        "isFirstChat": True,
                    },
                },
                "id": "req-welcome",
            })
            response = websocket.receive_json()

        # Top-level UIResponse wrapper
        assert "contextId" in response
        assert "conversationId" in response
        assert response["conversationId"] == "conv-welcome-test"
        welcome_text = response.get("response", "")
        assert "{user_name}" in welcome_text
        assert "Cisco Uber Assistant" in welcome_text
        assert "Book a demo or trial" in welcome_text
        assert "Velocity Hub" in welcome_text

        # Inner a2aResponse
        a2a = response.get("a2aResponse", {})
        assert a2a.get("jsonrpc") == "2.0"
        assert a2a.get("id") == "req-welcome"
        result = a2a.get("result", {})
        assert result.get("contextId") == "conv-welcome-test"

        # Welcome artifact
        artifacts = result.get("artifacts", [])
        assert len(artifacts) >= 1
        assert artifacts[0].get("name") == "welcome_message"
        assert artifacts[0].get("artifactId") == ""
        assert result.get("role") == "assistant"

        # Metadata inside result for welcome
        meta = result.get("metadata", {})
        assert meta.get("sessionId")
        assert meta.get("conversationId") == "conv-welcome-test"

    def test_a2a_missing_query(self, client: TestClient):
        """Empty or missing query (and not isFirstChat) returns A2A error -32422."""
        with client.websocket_connect("/ciscoua/api/v1/ws") as websocket:
            websocket.send_json({
                "jsonrpc": "2.0",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [],
                        "message_id": "msg-1",
                    },
                    "metadata": {"isFirstChat": False},
                },
                "id": "req-1",
            })
            response = websocket.receive_json()
        assert response.get("jsonrpc") == "2.0"
        assert "error" in response
        assert response["error"]["code"] == -32422
        assert "params" in response["error"]["message"].lower()
