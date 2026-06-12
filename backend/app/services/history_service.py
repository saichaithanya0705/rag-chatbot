from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.chroma_store import ChromaStore
from app.core.database import Database
from app.models.schemas import CitationPayload, ToolCallPayload
from app.services.conversation_context import looks_context_dependent
from app.services.history_serialization import (
    fallback_title,
    sanitize_title,
    serialize_message_row,
    serialize_session_row,
)
from app.services.history_memory_store import HistoryMemoryStore, MemoryTurn
from app.services.history_turn_persistence import persist_turn_records
from app.services.nvidia_client import NvidiaClient

LOGGER = logging.getLogger(__name__)
INTERACTIVE_MEMORY_EMBED_TIMEOUT_SECONDS = 20.0
TITLE_GENERATION_TIMEOUT_SECONDS = 12.0


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class HistoryService:
    def __init__(
        self,
        *,
        database: Database,
        chroma_store: ChromaStore,
        memory_collection_name: str,
        cross_session_memory_enabled: bool,
    ) -> None:
        self._database = database
        self._chroma_store = chroma_store
        self._memory_collection_name = memory_collection_name
        self._cross_session_memory_enabled = cross_session_memory_enabled
        self._memory_store = HistoryMemoryStore(
            collection_getter=self._memory_collection,
            cross_session_memory_enabled=cross_session_memory_enabled,
        )
        self._background_memory_tasks: set[asyncio.Task[None]] = set()

    def _memory_collection(self):
        return self._chroma_store.collection(self._memory_collection_name)

    def list_sessions(self, user_id: str) -> list[dict[str, str]]:
        self._backfill_missing_titles(user_id=user_id)
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, collection, updated_at
                FROM sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()

        return [serialize_session_row(row) for row in rows]

    def _backfill_missing_titles(self, *, user_id: str) -> None:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.id,
                    (
                        SELECT m.content
                        FROM messages m
                        WHERE m.session_id = s.id
                            AND m.user_id = s.user_id
                            AND m.role = 'user'
                        ORDER BY m.created_at ASC, m.id ASC
                        LIMIT 1
                    ) AS first_user_content
                FROM sessions s
                WHERE s.user_id = ?
                    AND s.title = 'New chat'
                    AND EXISTS (
                        SELECT 1
                        FROM messages m
                        WHERE m.session_id = s.id
                            AND m.user_id = s.user_id
                            AND m.role = 'user'
                    )
                """,
                (user_id,),
            ).fetchall()

            for row in rows:
                next_title = fallback_title(str(row["first_user_content"] or ""))
                if not next_title:
                    continue
                connection.execute(
                    """
                    UPDATE sessions
                    SET title = ?
                    WHERE id = ? AND user_id = ? AND title = 'New chat'
                    """,
                    (next_title, str(row["id"]), user_id),
                )

    def create_session(self, collection_id: str = "all-pdfs", *, user_id: str) -> dict[str, str]:
        reusable_session = self._reuse_empty_session(collection_id, user_id=user_id)
        if reusable_session is not None:
            return reusable_session

        session_id = str(uuid4())
        created_at = _utc_now_iso()

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (id, title, collection, user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, "New chat", collection_id, user_id, created_at, created_at),
            )

        return self.get_session_snapshot(session_id, user_id=user_id)

    def _reuse_empty_session(
        self,
        collection_id: str,
        *,
        user_id: str,
    ) -> dict[str, str] | None:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.id
                FROM sessions s
                LEFT JOIN messages m
                    ON m.session_id = s.id
                    AND m.user_id = s.user_id
                WHERE s.user_id = ?
                GROUP BY s.id
                HAVING COUNT(m.id) = 0
                ORDER BY s.updated_at DESC, s.id DESC
                """,
                (user_id,),
            ).fetchall()

            if not rows:
                return None

            reusable_session_id = str(rows[0]["id"])
            stale_session_ids = [str(row["id"]) for row in rows[1:]]
            if stale_session_ids:
                placeholders = ", ".join("?" for _ in stale_session_ids)
                connection.execute(
                    f"DELETE FROM sessions WHERE user_id = ? AND id IN ({placeholders})",
                    (user_id, *stale_session_ids),
                )

            connection.execute(
                """
                UPDATE sessions
                SET collection = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (collection_id, _utc_now_iso(), reusable_session_id, user_id),
            )

        return self.get_session_snapshot(reusable_session_id, user_id=user_id)

    def ensure_session(
        self,
        session_id: str,
        collection_id: str = "all-pdfs",
        *,
        user_id: str,
    ) -> dict[str, str]:
        existing = self._fetch_session_row(session_id, user_id=user_id)
        if existing:
            return serialize_session_row(existing)

        existing_other_user = self._fetch_session_row_any_user(session_id)
        if existing_other_user and str(existing_other_user["user_id"]) != user_id:
            raise ValueError("That session id is already in use. Start a new chat and try again.")

        created_at = _utc_now_iso()
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO sessions (id, title, collection, user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, "New chat", collection_id, user_id, created_at, created_at),
            )

        try:
            return self.get_session_snapshot(session_id, user_id=user_id)
        except FileNotFoundError:
            existing_other_user = self._fetch_session_row_any_user(session_id)
            if existing_other_user and str(existing_other_user["user_id"]) != user_id:
                raise ValueError("That session id is already in use. Start a new chat and try again.")
            raise

    def get_session_snapshot(self, session_id: str, *, user_id: str) -> dict[str, str]:
        row = self._fetch_session_row(session_id, user_id=user_id)
        if not row:
            raise FileNotFoundError(f"Session '{session_id}' was not found.")
        return serialize_session_row(row)

    def get_session_detail(self, session_id: str, *, user_id: str) -> dict[str, object] | None:
        row = self._fetch_session_row(session_id, user_id=user_id)
        if not row:
            return None

        snapshot = serialize_session_row(row)
        return {
            **snapshot,
            "messages": self.get_messages(session_id, user_id=user_id),
        }

    def get_messages(self, session_id: str, *, user_id: str) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    role,
                    content,
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
                    created_at
                FROM messages
                WHERE session_id = ? AND user_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (session_id, user_id),
            ).fetchall()

        return [serialize_message_row(row) for row in rows]

    def list_recent_messages(
        self,
        session_id: str,
        *,
        user_id: str,
        limit: int = 6,
    ) -> list[dict[str, str]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM messages
                WHERE session_id = ? AND user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (session_id, user_id, limit),
            ).fetchall()

        return [
            {
                "role": str(row["role"]),
                "content": str(row["content"]),
            }
            for row in reversed(rows)
        ]

    async def get_hybrid_memory(
        self,
        *,
        question: str,
        session_id: str | None,
        collection_id: str,
        nvidia_client: NvidiaClient,
        user_id: str,
    ) -> tuple[list[dict[str, str]], int]:
        if not looks_context_dependent(question):
            return [], 0

        if not session_id and not self._cross_session_memory_enabled:
            return [], 0

        recent_messages = (
            self.list_recent_messages(session_id, user_id=user_id, limit=6)
            if session_id
            else []
        )
        if not self._has_memory_candidates(session_id=session_id, user_id=user_id):
            return recent_messages, 0
        try:
            relevant_turns = await self._query_memory_turns(
                question=question,
                session_id=session_id,
                collection_id=collection_id,
                user_id=user_id,
                nvidia_client=nvidia_client,
                limit=6 if self._cross_session_memory_enabled else 3,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                "Hybrid memory retrieval failed for session %s; using recent session messages only.",
                session_id,
                exc_info=True,
            )
            return recent_messages, 0

        merged_messages: list[dict[str, str]] = []
        seen_messages: set[tuple[str, str]] = set()
        cross_session_turn_count = 0

        for memory_turn in relevant_turns:
            is_cross_session_turn = bool(memory_turn.session_id) and (
                session_id is None or memory_turn.session_id != session_id
            )
            if is_cross_session_turn:
                cross_session_turn_count += 1
            prompt_messages = (
                (("user", memory_turn.user_content),)
                if is_cross_session_turn
                else (
                    ("user", memory_turn.user_content),
                    ("assistant", memory_turn.assistant_content),
                )
            )
            for role, content in prompt_messages:
                if not content:
                    continue
                key = (role, content)
                if key in seen_messages:
                    continue
                seen_messages.add(key)
                merged_messages.append({"role": role, "content": content})

        for message in recent_messages:
            key = (message["role"], message["content"])
            if key in seen_messages:
                continue
            seen_messages.add(key)
            merged_messages.append(message)

        return merged_messages, cross_session_turn_count

    def _has_memory_candidates(self, *, session_id: str | None, user_id: str) -> bool:
        if self._cross_session_memory_enabled:
            where_filter: dict[str, object] = {"user_id": user_id}
        elif session_id:
            where_filter = {"$and": [{"user_id": user_id}, {"session_id": session_id}]}
        else:
            return False

        rows = self._memory_collection().get(
            where=where_filter,
            limit=1,
            include=["metadatas"],
        )
        return bool(rows.get("ids"))

    async def save_turn(
        self,
        *,
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
        nvidia_client: NvidiaClient,
        cross_session_memory_used: int = 0,
        user_id: str,
    ) -> None:
        await asyncio.to_thread(
            self.ensure_session,
            session_id,
            collection_id,
            user_id=user_id,
        )
        user_timestamp = datetime.now(UTC)
        assistant_timestamp = user_timestamp + timedelta(microseconds=1)
        memory_id = str(uuid4())

        await asyncio.to_thread(
            self._persist_turn_records,
            session_id=session_id,
            collection_id=collection_id,
            collection_label=collection_label,
            user_content=user_content,
            assistant_content=assistant_content,
            citations=citations,
            answer_trace=answer_trace,
            tool_call=tool_call,
            web_search_requested=web_search_requested,
            web_search_used=web_search_used,
            offline_warning=offline_warning,
            model_thinking=model_thinking,
            thinking_requested=thinking_requested,
            cross_session_memory_used=cross_session_memory_used,
            memory_id=memory_id,
            user_timestamp=user_timestamp.isoformat(),
            assistant_timestamp=assistant_timestamp.isoformat(),
            user_id=user_id,
        )

        memory_task = asyncio.create_task(
            self._store_memory_turn(
                memory_id=memory_id,
                session_id=session_id,
                collection_id=collection_id,
                created_at=assistant_timestamp.isoformat(),
                user_id=user_id,
                user_content=user_content,
                assistant_content=assistant_content,
                nvidia_client=nvidia_client,
            )
        )
        self._background_memory_tasks.add(memory_task)
        memory_task.add_done_callback(
            lambda task, *, tracked_session_id=session_id: self._finalize_memory_index_task(
                task,
                session_id=tracked_session_id,
            )
        )

    def delete_session(self, session_id: str, *, user_id: str) -> None:
        self._memory_collection().delete(
            where={"$and": [{"session_id": session_id}, {"user_id": user_id}]}
        )
        with self._database.connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            )

    def should_generate_title(self, session_id: str, *, user_id: str) -> bool:
        snapshot = self.get_session_snapshot(session_id, user_id=user_id)
        if snapshot["title"] != "New chat":
            return False

        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS user_message_count
                FROM messages
                WHERE session_id = ? AND role = 'user' AND user_id = ?
                """,
                (session_id, user_id),
            ).fetchone()

        return int(row["user_message_count"]) == 1

    async def generate_title(
        self,
        session_id: str,
        first_message: str,
        nvidia_client: NvidiaClient,
        *,
        user_id: str,
    ) -> str | None:
        prompt = (
            "Summarize this user message in five words or fewer as a chat title. "
            "Reply with the title only.\n\n"
            f"Message: {first_message}"
        )
        system_prompt = (
            "You write concise chat session titles. "
            "Do not use quotation marks, numbering, or extra commentary."
        )
        fallback_title_value = fallback_title(first_message)

        try:
            raw_title = await nvidia_client.generate_answer(
                prompt=prompt,
                system_prompt=system_prompt,
                options={
                    "num_predict": 12,
                    "temperature": 0,
                    "stop": ["\n"],
                },
                timeout=TITLE_GENERATION_TIMEOUT_SECONDS,
            )
        except Exception:
            title = fallback_title_value
        else:
            title = sanitize_title(raw_title.response) or fallback_title_value

        if not title:
            return None

        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE sessions
                SET title = ?
                WHERE id = ? AND title = 'New chat' AND user_id = ?
                """,
                (title, session_id, user_id),
            )
            if cursor.rowcount == 0:
                row = connection.execute(
                    """
                    SELECT title
                    FROM sessions
                    WHERE id = ? AND user_id = ?
                    """,
                    (session_id, user_id),
                ).fetchone()
                return str(row["title"]) if row and row["title"] else None

        return title

    async def _query_memory_turns(
        self,
        *,
        question: str,
        session_id: str | None,
        collection_id: str,
        user_id: str,
        nvidia_client: NvidiaClient,
        limit: int,
    ) -> list[MemoryTurn]:
        query_embedding = (
            await nvidia_client.embed_texts(
                [question],
                input_type="query",
                timeout=INTERACTIVE_MEMORY_EMBED_TIMEOUT_SECONDS,
            )
        )[0]
        return await asyncio.to_thread(
            self._memory_store.query_turns_by_embedding,
            query_embedding=query_embedding,
            session_id=session_id,
            collection_id=collection_id,
            user_id=user_id,
            limit=limit,
        )

    def get_memory_stats(self, *, user_id: str) -> dict[str, object]:
        return self._memory_store.get_stats(user_id=user_id)

    async def _store_memory_turn(
        self,
        *,
        memory_id: str,
        session_id: str,
        collection_id: str,
        created_at: str,
        user_id: str,
        user_content: str,
        assistant_content: str,
        nvidia_client: NvidiaClient,
    ) -> None:
        memory_text = f"User: {user_content}"
        memory_embedding = (await nvidia_client.embed_texts([memory_text], input_type="passage"))[0]
        await asyncio.to_thread(
            self._memory_store.upsert_turn,
            memory_id=memory_id,
            session_id=session_id,
            collection_id=collection_id,
            created_at=created_at,
            user_id=user_id,
            user_content=user_content,
            assistant_content=assistant_content,
            memory_text=memory_text,
            memory_embedding=memory_embedding,
        )

    def _finalize_memory_index_task(
        self,
        task: asyncio.Task[None],
        *,
        session_id: str,
    ) -> None:
        self._background_memory_tasks.discard(task)
        try:
            task.result()
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                "Cross-session memory indexing failed for session %s; keeping persisted chat turn.",
                session_id,
                exc_info=True,
            )

    def _delete_memory_turn(self, memory_id: str) -> None:
        self._memory_store.delete_turn(memory_id)

    def _persist_turn_records(
        self,
        *,
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
        persist_turn_records(
            database=self._database,
            session_id=session_id,
            collection_id=collection_id,
            collection_label=collection_label,
            user_content=user_content,
            assistant_content=assistant_content,
            citations=citations,
            answer_trace=answer_trace,
            tool_call=tool_call,
            web_search_requested=web_search_requested,
            web_search_used=web_search_used,
            offline_warning=offline_warning,
            model_thinking=model_thinking,
            thinking_requested=thinking_requested,
            cross_session_memory_used=cross_session_memory_used,
            memory_id=memory_id,
            user_timestamp=user_timestamp,
            assistant_timestamp=assistant_timestamp,
            user_id=user_id,
        )

    def _fetch_session_row(self, session_id: str, *, user_id: str):
        with self._database.connect() as connection:
            return connection.execute(
                """
                SELECT id, title, collection, updated_at
                FROM sessions
                WHERE id = ? AND user_id = ?
                """,
                (session_id, user_id),
            ).fetchone()

    def _fetch_session_row_any_user(self, session_id: str):
        with self._database.connect() as connection:
            return connection.execute(
                """
                SELECT id, title, collection, updated_at, user_id
                FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
