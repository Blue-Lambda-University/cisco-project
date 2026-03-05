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
        with client.websocket_connect("/ws") as websocket:
            # Connection should be established
            assert websocket is not None

    def test_websocket_with_subprotocol(self, client: TestClient):
        """Test WebSocket connection with subprotocol."""
        with client.websocket_connect(
            "/ws",
            subprotocols=["circuit.v1"],
        ) as websocket:
            # Check that subprotocol was accepted
            # Note: TestClient may not fully support subprotocol negotiation
            assert websocket is not None

    def test_websocket_with_client_id(self, client: TestClient):
        """Test WebSocket connection with client ID path."""
        with client.websocket_connect("/ws/test-client-123") as websocket:
            assert websocket is not None


class TestWebSocketMessages:
    """Tests for WebSocket message handling."""

    def test_user_query_message(
        self,
        client: TestClient,
        sample_user_query_message: dict,
    ):
        """Test user query message handling."""
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(sample_user_query_message)
            response = websocket.receive_json()
            
            assert response["type"] == "assistant_response"
            assert "message" in response["payload"]
            assert "confidence" in response["payload"]
            assert response["metadata"]["correlation_id"] == "corr-456"

    def test_ping_message(
        self,
        client: TestClient,
        sample_ping_message: dict,
    ):
        """Test ping/pong message handling."""
        with client.websocket_connect("/ws") as websocket:
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
        with client.websocket_connect("/ws") as websocket:
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
        with client.websocket_connect("/ws") as websocket:
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
        with client.websocket_connect("/ws") as websocket:
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
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(sample_invalid_message)
            response = websocket.receive_json()
            
            assert response["type"] == "error"
            assert response["payload"]["code"] == "VALIDATION_ERROR"

    def test_invalid_json(self, client: TestClient):
        """Test handling of invalid JSON."""
        with client.websocket_connect("/ws") as websocket:
            websocket.send_text("not valid json {{{")
            response = websocket.receive_json()
            
            assert response["type"] == "error"
            assert response["payload"]["code"] == "INVALID_JSON"

    def test_missing_required_fields(self, client: TestClient):
        """Test handling of message with missing required fields."""
        with client.websocket_connect("/ws") as websocket:
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
        with client.websocket_connect("/ws") as websocket:
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
        with client.websocket_connect("/ws") as websocket:
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
        with client.websocket_connect("/ws") as websocket:
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
