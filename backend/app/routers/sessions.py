from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.dependencies import get_container, get_user_id
from app.models.schemas import CreateSessionRequest, SessionDetailResponse, SessionSummaryPayload
from app.services.container import ServiceContainer

router = APIRouter(prefix="/sessions", tags=["sessions"])

FILENAME_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")


def _export_filename(title: str) -> str:
    slug = FILENAME_SANITIZE_PATTERN.sub("-", title.lower()).strip("-")
    return f"session-{slug or 'chat'}.json"


@router.get("", response_model=list[SessionSummaryPayload])
def list_sessions(
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> list[SessionSummaryPayload]:
    sessions = container.history_service.list_sessions(user_id=user_id)
    return [SessionSummaryPayload(**session) for session in sessions]


@router.post("", response_model=SessionDetailResponse)
def create_session(
    request: CreateSessionRequest,
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> SessionDetailResponse:
    session = container.history_service.create_session(collection_id=request.collection_id, user_id=user_id)
    detail = container.history_service.get_session_detail(session["id"], user_id=user_id)
    if not detail:
        raise HTTPException(status_code=500, detail="Session creation failed.")
    return SessionDetailResponse(**detail)


@router.get("/{session_id}/export")
def export_session(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> Response:
    detail = container.history_service.get_session_detail(session_id, user_id=user_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' was not found.")

    payload = {
        "session": {
            "id": detail["id"],
            "title": detail["title"],
            "collectionId": detail["collectionId"],
            "group": detail["group"],
            "updatedAt": detail["updatedAt"],
        },
        "messages": detail["messages"],
        "exportedAt": datetime.now(UTC).isoformat(),
    }
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{_export_filename(str(detail["title"]))}"',
        },
    )


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> SessionDetailResponse:
    detail = container.history_service.get_session_detail(session_id, user_id=user_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' was not found.")
    return SessionDetailResponse(**detail)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> Response:
    detail = container.history_service.get_session_detail(session_id, user_id=user_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' was not found.")

    container.history_service.delete_session(session_id, user_id=user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
