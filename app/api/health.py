"""Health check endpoints for Kubernetes probes."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter

from app.dependencies.providers import (
    ConnectionManagerDep,
    ResponseLoaderDep,
    SettingsDep,
)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(
    settings: SettingsDep,
    connection_manager: ConnectionManagerDep,
) -> dict[str, Any]:
    """
    Health check endpoint for Kubernetes liveness probe.
    
    Returns basic health information about the service.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "mock-websocket-server",
        "environment": settings.environment,
    }


@router.get("/health/ready")
async def readiness_check(
    settings: SettingsDep,
    connection_manager: ConnectionManagerDep,
    response_loader: ResponseLoaderDep,
) -> dict[str, Any]:
    """
    Readiness check endpoint for Kubernetes readiness probe.
    
    Verifies that the service is ready to accept traffic by checking
    that all dependencies are initialized.
    """
    checks = {
        "responses_loaded": response_loader.is_loaded,
        "connection_manager_ready": connection_manager is not None,
    }
    
    all_ready = all(checks.values())
    
    return {
        "status": "ready" if all_ready else "not_ready",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": checks,
    }


@router.get("/health/live")
async def liveness_check() -> dict[str, str]:
    """
    Simple liveness check endpoint.
    
    This is the most basic health check - if the service can respond,
    it's alive.
    """
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/stats")
async def get_stats(
    connection_manager: ConnectionManagerDep,
    response_loader: ResponseLoaderDep,
) -> dict[str, Any]:
    """
    Get service statistics.
    
    Provides metrics about the current state of the service including
    connection counts and configuration information.
    """
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "connections": connection_manager.get_stats(),
        "responses": {
            "version": response_loader.get_version(),
            "types_available": response_loader.get_all_response_types(),
        },
    }
