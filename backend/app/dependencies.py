from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status

if TYPE_CHECKING:
    from app.services.container import ServiceContainer


def get_container(request: Request) -> ServiceContainer:
    container = getattr(request.app.state, "container", None)
    if container is not None:
        return container

    startup_error = getattr(request.app.state, "container_startup_error", None)
    if startup_error is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The service failed during startup. Check backend logs for details.",
        )

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="The service is still starting up. Try again shortly.",
    )


def get_user_id(request: Request) -> str:
    user_id = request.headers.get("x-user-id", "").strip()
    if not user_id:
        user_id = request.query_params.get("userId", "").strip()
    if not user_id:
        user_id = request.query_params.get("x-user-id", "").strip()
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The x-user-id header is required.",
        )
    if len(user_id) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The x-user-id header is too long.",
        )
    return user_id
