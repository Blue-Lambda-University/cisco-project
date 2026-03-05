"""WebSocket connection manager for tracking active connections."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from app.logging.setup import get_logger

logger = get_logger()


@dataclass
class ConnectionInfo:
    """Information about a single WebSocket connection."""

    connection_id: str
    websocket: WebSocket
    client_ip: str
    subprotocol: str | None
    connected_at: datetime = field(default_factory=datetime.utcnow)
    subscriptions: set[str] = field(default_factory=set)
    message_count: int = 0
    last_message_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "connection_id": self.connection_id,
            "client_ip": self.client_ip,
            "subprotocol": self.subprotocol,
            "connected_at": self.connected_at.isoformat(),
            "subscriptions": list(self.subscriptions),
            "message_count": self.message_count,
            "last_message_at": (
                self.last_message_at.isoformat() if self.last_message_at else None
            ),
        }


class ConnectionManager:
    """
    Manages WebSocket connections lifecycle.
    
    Handles connection tracking, subscription management, and provides
    utilities for broadcasting messages to connected clients.
    """

    def __init__(self, max_connections: int = 1000) -> None:
        """
        Initialize the connection manager.
        
        Args:
            max_connections: Maximum number of concurrent connections allowed.
        """
        self._connections: dict[str, ConnectionInfo] = {}
        self._max_connections = max_connections
        self._logger = logger.bind(component="connection_manager")

    @property
    def active_count(self) -> int:
        """Get the number of active connections."""
        return len(self._connections)

    @property
    def max_connections(self) -> int:
        """Get the maximum allowed connections."""
        return self._max_connections

    def is_at_capacity(self) -> bool:
        """Check if the manager is at connection capacity."""
        return self.active_count >= self._max_connections

    def generate_connection_id(self) -> str:
        """Generate a unique connection ID."""
        return str(uuid.uuid4())

    async def connect(
        self,
        websocket: WebSocket,
        subprotocol: str | None = None,
    ) -> ConnectionInfo:
        """
        Register a new WebSocket connection.
        
        Args:
            websocket: The WebSocket instance.
            subprotocol: The negotiated subprotocol (if any).
            
        Returns:
            ConnectionInfo for the new connection.
            
        Raises:
            ConnectionError: If max connections exceeded.
        """
        if self.is_at_capacity():
            self._logger.warning(
                "connection_rejected",
                reason="max_connections_exceeded",
                max_connections=self._max_connections,
                current_connections=self.active_count,
            )
            raise ConnectionError("Maximum connections exceeded")

        connection_id = self.generate_connection_id()
        client_ip = self._get_client_ip(websocket)

        connection_info = ConnectionInfo(
            connection_id=connection_id,
            websocket=websocket,
            client_ip=client_ip,
            subprotocol=subprotocol,
        )

        self._connections[connection_id] = connection_info

        self._logger.info(
            "connection_established",
            connection_id=connection_id,
            client_ip=client_ip,
            subprotocol=subprotocol,
            total_connections=self.active_count,
        )

        return connection_info

    async def disconnect(self, connection_id: str) -> None:
        """
        Remove a WebSocket connection.
        
        Args:
            connection_id: The connection ID to remove.
        """
        if connection_id in self._connections:
            connection_info = self._connections.pop(connection_id)
            
            self._logger.info(
                "connection_closed",
                connection_id=connection_id,
                client_ip=connection_info.client_ip,
                message_count=connection_info.message_count,
                duration_seconds=(
                    datetime.utcnow() - connection_info.connected_at
                ).total_seconds(),
                total_connections=self.active_count,
            )

    def get_connection(self, connection_id: str) -> ConnectionInfo | None:
        """Get connection info by ID."""
        return self._connections.get(connection_id)

    def update_message_count(self, connection_id: str) -> None:
        """Increment message count for a connection."""
        if connection_id in self._connections:
            conn = self._connections[connection_id]
            conn.message_count += 1
            conn.last_message_at = datetime.utcnow()

    def add_subscription(self, connection_id: str, topic: str) -> None:
        """Add a topic subscription to a connection."""
        if connection_id in self._connections:
            self._connections[connection_id].subscriptions.add(topic)
            self._logger.debug(
                "subscription_added",
                connection_id=connection_id,
                topic=topic,
            )

    def remove_subscription(self, connection_id: str, topic: str) -> None:
        """Remove a topic subscription from a connection."""
        if connection_id in self._connections:
            self._connections[connection_id].subscriptions.discard(topic)
            self._logger.debug(
                "subscription_removed",
                connection_id=connection_id,
                topic=topic,
            )

    def get_subscribers(self, topic: str) -> list[ConnectionInfo]:
        """Get all connections subscribed to a topic."""
        return [
            conn for conn in self._connections.values()
            if topic in conn.subscriptions
        ]

    async def send_to_connection(self, connection_id: str, text: str) -> bool:
        """
        Send a text message to a specific connection by ID.
        Used by the webhook handler to push the orchestrator response to the right client.
        Returns True if sent, False if connection not found or send failed.
        """
        conn = self._connections.get(connection_id)
        if conn is None:
            self._logger.debug("send_to_connection_not_found", connection_id=connection_id)
            return False
        try:
            await conn.websocket.send_text(text)
            return True
        except Exception as e:
            self._logger.warning(
                "send_to_connection_failed",
                connection_id=connection_id,
                error=str(e),
            )
            return False

    async def broadcast(self, message: str, topic: str | None = None) -> int:
        """
        Broadcast a message to connections.
        
        Args:
            message: The message to broadcast.
            topic: If provided, only send to subscribers of this topic.
            
        Returns:
            Number of connections the message was sent to.
        """
        if topic:
            targets = self.get_subscribers(topic)
        else:
            targets = list(self._connections.values())

        sent_count = 0
        for conn in targets:
            try:
                await conn.websocket.send_text(message)
                sent_count += 1
            except Exception as e:
                self._logger.warning(
                    "broadcast_failed",
                    connection_id=conn.connection_id,
                    error=str(e),
                )

        return sent_count

    def get_stats(self) -> dict[str, Any]:
        """Get connection statistics."""
        return {
            "active_connections": self.active_count,
            "max_connections": self._max_connections,
            "capacity_used_percent": (
                (self.active_count / self._max_connections) * 100
                if self._max_connections > 0 else 0
            ),
        }

    def _get_client_ip(self, websocket: WebSocket) -> str:
        """Extract client IP from WebSocket connection."""
        # Check for forwarded IP (behind load balancer)
        forwarded = websocket.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        # Fall back to direct client
        if websocket.client:
            return websocket.client.host
        
        return "unknown"
