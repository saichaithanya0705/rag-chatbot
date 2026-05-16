from __future__ import annotations

import json
from uuid import uuid4

from app.core.database import Database
from app.models.schemas import CitationPayload, ToolCallPayload


def persist_turn_records(
    *,
    database: Database,
    session_id: str,
    collection_id: str,
    collection_label: str,
    user_content: str,
    assistant_content: str,
    citations: list[CitationPayload],
    answer_trace: list[dict[str, object]],
    tool_call: ToolCallPayload | None,
    web_search_requested: bool,
    web_search_used: bool,
    offline_warning: str | None,
    model_thinking: str | None,
    thinking_requested: bool,
    cross_session_memory_used: int,
    memory_id: str,
    user_timestamp: str,
    assistant_timestamp: str,
    user_id: str,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE sessions
            SET collection = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (collection_id, assistant_timestamp, session_id, user_id),
        )
        connection.executemany(
            """
            INSERT INTO messages (
                id,
                session_id,
                role,
                content,
                user_id,
                collection_id,
                collection_label,
                citations,
                answer_trace,
                tool_call,
                model_thinking,
                web_search_requested,
                web_search_used,
                offline_warning,
                thinking_requested,
                cross_session_memory_used,
                embedding_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(uuid4()),
                    session_id,
                    "user",
                    user_content,
                    user_id,
                    collection_id,
                    collection_label,
                    json.dumps([]),
                    json.dumps([]),
                    None,
                    None,
                    int(web_search_requested),
                    0,
                    None,
                    int(thinking_requested),
                    0,
                    memory_id,
                    user_timestamp,
                ),
                (
                    str(uuid4()),
                    session_id,
                    "assistant",
                    assistant_content,
                    user_id,
                    collection_id,
                    collection_label,
                    json.dumps([citation.model_dump(by_alias=True) for citation in citations]),
                    json.dumps(answer_trace),
                    json.dumps(tool_call.model_dump()) if tool_call is not None else None,
                    model_thinking,
                    int(web_search_requested),
                    int(web_search_used),
                    offline_warning,
                    int(thinking_requested),
                    int(cross_session_memory_used),
                    memory_id,
                    assistant_timestamp,
                ),
            ],
        )
