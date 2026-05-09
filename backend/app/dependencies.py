from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.services.container import ServiceContainer


def get_container(request: Request) -> ServiceContainer:
    return request.app.state.container


def get_user_id(request: Request) -> str:
    user_id = request.headers.get("x-user-id", "").strip()
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
