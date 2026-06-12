from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.dependencies import get_container, get_user_id

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

router = APIRouter(prefix="/events", tags=["events"])


def _snapshot(document: dict[str, Any]) -> tuple[str, int, str | None]:
    return (
        str(document["status"]),
        int(document["progress"]),
        str(document["error_message"]) if document.get("error_message") else None,
    )


def _serialize_event(document: dict[str, Any]) -> dict[str, object]:
    payload: dict[str, object] = {
        "documentId": str(document["id"]),
        "status": str(document["status"]),
        "progress": int(document["progress"]),
    }
    if document.get("error_message"):
        payload["error"] = str(document["error_message"])
    return payload


def _format_sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.get("/ingestion-progress")
async def stream_ingestion_progress(
    request: Request,
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> StreamingResponse:
    async def event_stream():
        known_documents: dict[str, tuple[str, int, str | None]] = {}
        idle_since: float | None = None
        last_heartbeat_at = time.monotonic()

        while True:
            if await request.is_disconnected():
                break
            documents = {
                str(document["id"]): document
                for document in await asyncio.to_thread(
                    container.document_service.list_documents,
                    user_id=user_id,
                )
            }
            active_documents = {
                document_id: document
                for document_id, document in documents.items()
                if str(document["status"]) not in {"indexed", "error"}
            }

            emitted = False
            for document_id, document in active_documents.items():
                snapshot = _snapshot(document)
                if known_documents.get(document_id) == snapshot:
                    continue
                known_documents[document_id] = snapshot
                emitted = True
                yield _format_sse(_serialize_event(document))

            finished_ids = [document_id for document_id in known_documents if document_id not in active_documents]
            for document_id in finished_ids:
                final_document = documents.get(document_id)
                if final_document is not None:
                    emitted = True
                    yield _format_sse(_serialize_event(final_document))
                known_documents.pop(document_id, None)

            if active_documents:
                idle_since = None
            else:
                if idle_since is None:
                    idle_since = time.monotonic()
                elif time.monotonic() - idle_since >= 30:
                    break

            now = time.monotonic()
            if not emitted and now - last_heartbeat_at >= 15:
                last_heartbeat_at = now
                yield ": ping\n\n"

            await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
