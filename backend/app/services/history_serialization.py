from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.models.schemas import CitationPayload, ToolCallPayload
from app.services.answer_trace import build_answer_trace


def resolve_session_group(updated_at: str) -> str:
    parsed = datetime.fromisoformat(updated_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    local_tz = datetime.now().astimezone().tzinfo
    today = datetime.now(local_tz).date()
    session_date = parsed.astimezone(local_tz).date()
    delta_days = (today - session_date).days

    if delta_days <= 0:
        return "Today"
    if delta_days == 1:
        return "Yesterday"
    if delta_days <= 7:
        return "Last 7 days"
    return "Older"


def sanitize_title(value: str) -> str:
    cleaned = " ".join(value.replace("\n", " ").strip().strip("\"'").split())
    if not cleaned:
        return ""
    return cleaned[:48]


def fallback_title(value: str) -> str:
    cleaned = " ".join(value.replace("\n", " ").strip().strip("\"'").split())
    cleaned = cleaned.rstrip(".,:;!?")
    if not cleaned:
        return ""
    if len(cleaned) <= 48:
        return cleaned

    clipped = cleaned[:48].rstrip()
    last_space = clipped.rfind(" ")
    if last_space >= 24:
        clipped = clipped[:last_space]
    return clipped.rstrip(" ,;:-")


def serialize_session_row(row: Any) -> dict[str, str]:
    updated_at = str(row["updated_at"])
    return {
        "id": str(row["id"]),
        "title": str(row["title"]),
        "group": resolve_session_group(updated_at),
        "collectionId": str(row["collection"]),
        "updatedAt": updated_at,
    }


def serialize_message_row(row: Any) -> dict[str, object]:
    raw_citations = json.loads(str(row["citations"])) if row["citations"] else []
    citations = [CitationPayload.model_validate(item).model_dump(by_alias=True) for item in raw_citations]
    tool_call = (
        ToolCallPayload.model_validate(json.loads(str(row["tool_call"]))).model_dump(by_alias=True)
        if row["tool_call"]
        else None
    )
    stored_trace = json.loads(str(row["answer_trace"])) if row["answer_trace"] else None
    answer_trace = (
        stored_trace
        if isinstance(stored_trace, list)
        else [
            step.model_dump(by_alias=True)
            for step in build_answer_trace(
                pdf_context_count=sum(
                    1
                    for citation in raw_citations
                    if str(citation.get("kind", "pdf")) == "pdf"
                ),
                citations=[CitationPayload.model_validate(item) for item in raw_citations],
                cross_session_memory_used=int(row["cross_session_memory_used"] or 0),
                collection_id=str(row["collection_id"] or "all-pdfs"),
                collection_label=str(row["collection_label"] or "All PDFs"),
                tool_call=ToolCallPayload.model_validate(json.loads(str(row["tool_call"]))) if row["tool_call"] else None,
                web_search_requested=bool(row["web_search_requested"]),
                web_search_used=bool(row["web_search_used"]),
                offline_warning=str(row["offline_warning"]) if row["offline_warning"] else None,
            )
        ]
    )
    return {
        "id": str(row["id"]),
        "role": str(row["role"]),
        "content": str(row["content"]),
        "citations": citations,
        "answerTrace": answer_trace,
        "collectionId": str(row["collection_id"] or "all-pdfs"),
        "collectionLabel": str(row["collection_label"] or "All PDFs"),
        "toolCall": tool_call,
        "webSearchRequested": bool(row["web_search_requested"]),
        "webSearchUsed": bool(row["web_search_used"]),
        "offlineWarning": str(row["offline_warning"]) if row["offline_warning"] else None,
        "crossSessionMemoryUsed": int(row["cross_session_memory_used"] or 0),
        "modelThinking": str(row["model_thinking"]) if row["model_thinking"] else None,
        "thinkingRequested": bool(row["thinking_requested"]),
        "createdAt": str(row["created_at"]),
    }
