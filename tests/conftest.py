"""Pytest fixtures for testing."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings."""
    return Settings(
        environment="development",
        log_level="DEBUG",
        latency_enabled=False,  # Disable latency for faster tests
        max_connections=100,
        canned_responses_path="app/responses/canned_responses.json",
    )


@pytest.fixture
def app(test_settings: Settings):
    """Create test application."""
    from app.dependencies.providers import reset_singletons
    reset_singletons()
    return create_app(settings=test_settings)


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def sample_user_query_message() -> dict:
    """Sample user query message (no session_id so server creates one)."""
    return {
        "type": "user_query",
        "payload": {
            "query": "What is my account balance?",
            "language": "en",
        },
        "metadata": {
            "correlation_id": "corr-456",
        },
    }


@pytest.fixture
def sample_ping_message() -> dict:
    """Sample ping message (no session_id so server creates one)."""
    return {
        "type": "ping",
        "payload": {
            "client_timestamp": "2024-01-15T10:30:00Z",
        },
        "metadata": {},
    }


@pytest.fixture
def sample_get_history_message() -> dict:
    """Sample get history message (no session_id so server creates one)."""
    return {
        "type": "get_history",
        "payload": {
            "limit": 10,
            "offset": 0,
        },
        "metadata": {},
    }


@pytest.fixture
def sample_orchestrate_message() -> dict:
    """Sample orchestrate message (no session_id so server creates one)."""
    return {
        "type": "orchestrate",
        "payload": {
            "action": "search_knowledge_base",
            "parameters": {"query": "product info"},
            "agents": ["findability_agent"],
        },
        "metadata": {},
    }


@pytest.fixture
def sample_subscribe_message() -> dict:
    """Sample subscribe message (no session_id so server creates one)."""
    return {
        "type": "subscribe",
        "payload": {
            "topics": ["notifications", "updates"],
        },
        "metadata": {},
    }


@pytest.fixture
def sample_invalid_message() -> dict:
    """Sample invalid message (unknown type)."""
    return {
        "type": "unknown_type",
        "payload": {},
        "metadata": {},
    }
