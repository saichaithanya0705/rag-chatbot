from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.chroma_store import ChromaStore
from app.core.database import Database
from app.models.schemas import CitationPayload, ToolCallPayload
from app.services.answer_trace import build_answer_trace
from app.services.conversation_context import looks_context_dependent
from app.services.ollama_client import OllamaClient

LOGGER = logging.getLogger(__name__)
INTERACTIVE_MEMORY_EMBED_TIMEOUT_SECONDS = 20.0
TITLE_GENERATION_TIMEOUT_SECONDS = 12.0


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _resolve_session_group(updated_at: str) -> str:
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


@dataclass
class MemoryTurn:
    user_content: str
    assistant_content: str
    session_id: str
    collection_id: str


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

        return [self._serialize_session_row(row) for row in rows]

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
                fallback_title = self._fallback_title(str(row["first_user_content"] or ""))
                if not fallback_title:
                    continue
                connection.execute(
                    """
                    UPDATE sessions
                    SET title = ?
                    WHERE id = ? AND user_id = ? AND title = 'New chat'
                    """,
                    (fallback_title, str(row["id"]), user_id),
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
            return self._serialize_session_row(existing)

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
        return self._serialize_session_row(row)

    def get_session_detail(self, session_id: str, *, user_id: str) -> dict[str, object] | None:
        row = self._fetch_session_row(session_id, user_id=user_id)
        if not row:
            return None

        snapshot = self._serialize_session_row(row)
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

        return [self._serialize_message_row(row) for row in rows]

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
        ollama_client: OllamaClient,
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
                ollama_client=ollama_client,
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
        ollama_client: OllamaClient,
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
                ollama_client=ollama_client,
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
        ollama_client: OllamaClient,
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
        fallback_title = self._fallback_title(first_message)

        try:
            raw_title = await ollama_client.generate_answer(
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
            title = fallback_title
        else:
            title = self._sanitize_title(raw_title.response) or fallback_title

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
        ollama_client: OllamaClient,
        limit: int,
    ) -> list[MemoryTurn]:
        query_embedding = (
            await ollama_client.embed_texts(
                [question],
                timeout=INTERACTIVE_MEMORY_EMBED_TIMEOUT_SECONDS,
            )
        )[0]
        return await asyncio.to_thread(
            self._query_memory_turns_by_embedding,
            query_embedding=query_embedding,
            session_id=session_id,
            collection_id=collection_id,
            user_id=user_id,
            limit=limit,
        )

    def _query_memory_turns_by_embedding(
        self,
        *,
        query_embedding: list[float],
        session_id: str | None,
        collection_id: str,
        user_id: str,
        limit: int,
    ) -> list[MemoryTurn]:
        collection = self._memory_collection()
        where_filter: dict[str, object]
        if self._cross_session_memory_enabled:
            where_filter = {"user_id": user_id}
        elif session_id:
            where_filter = {"$and": [{"user_id": user_id}, {"session_id": session_id}]}
        else:
            return []

        rows = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(limit * 4, 12),
            where=where_filter,
            include=["metadatas", "distances"],
        )

        metadatas = rows.get("metadatas", [[]])[0]
        distances = rows.get("distances", [[]])[0]
        memory_turns: list[MemoryTurn] = []
        for metadata, distance in zip(metadatas, distances, strict=False):
            if distance is not None and float(distance) > 1.2:
                continue
            memory_session_id = str(metadata.get("session_id", ""))
            memory_collection_id = str(metadata.get("collection_id", "all-pdfs"))
            if (
                self._cross_session_memory_enabled
                and collection_id != "all-pdfs"
                and memory_session_id != session_id
                and memory_collection_id not in {collection_id, "all-pdfs"}
            ):
                continue
            if (
                self._cross_session_memory_enabled
                and session_id
                and collection_id != "all-pdfs"
                and memory_session_id != session_id
                and memory_collection_id not in {collection_id, "all-pdfs"}
            ):
                continue

            user_content = str(metadata.get("user_content", "")).strip()
            assistant_content = str(metadata.get("assistant_content", "")).strip()
            if not user_content and not assistant_content:
                continue
            memory_turns.append(
                MemoryTurn(
                    user_content=user_content,
                    assistant_content=assistant_content,
                    session_id=memory_session_id,
                    collection_id=memory_collection_id,
                )
            )
            if len(memory_turns) >= limit:
                break

        return memory_turns

    def get_memory_stats(self, *, user_id: str) -> dict[str, object]:
        rows = self._memory_collection().get(where={"user_id": user_id}, include=["metadatas"])
        metadatas = rows.get("metadatas", [])
        timestamps = [
            str(metadata.get("created_at"))
            for metadata in metadatas
            if metadata and metadata.get("created_at")
        ]
        unique_sessions = {
            str(metadata.get("session_id"))
            for metadata in metadatas
            if metadata and metadata.get("session_id")
        }
        return {
            "totalTurns": len(rows.get("ids", [])),
            "uniqueSessions": len(unique_sessions),
            "oldestTimestamp": min(timestamps) if timestamps else None,
            "newestTimestamp": max(timestamps) if timestamps else None,
        }

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
        ollama_client: OllamaClient,
    ) -> None:
        memory_text = f"User: {user_content}"
        memory_embedding = (await ollama_client.embed_texts([memory_text]))[0]
        await asyncio.to_thread(
            self._upsert_memory_turn,
            memory_id,
            session_id,
            collection_id,
            created_at,
            user_id,
            user_content,
            assistant_content,
            memory_text,
            memory_embedding,
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

    def _upsert_memory_turn(
        self,
        memory_id: str,
        session_id: str,
        collection_id: str,
        created_at: str,
        user_id: str,
        user_content: str,
        assistant_content: str,
        memory_text: str,
        memory_embedding: list[float],
    ) -> None:
        self._memory_collection().upsert(
            ids=[memory_id],
            documents=[memory_text],
            embeddings=[memory_embedding],
            metadatas=[
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "collection_id": collection_id,
                    "created_at": created_at,
                    "user_content": user_content,
                    "assistant_content": assistant_content,
                }
            ],
        )

    def _delete_memory_turn(self, memory_id: str) -> None:
        self._memory_collection().delete(ids=[memory_id])

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
        with self._database.connect() as connection:
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

    @staticmethod
    def _sanitize_title(value: str) -> str:
        cleaned = " ".join(value.replace("\n", " ").strip().strip("\"'").split())
        if not cleaned:
            return ""
        return cleaned[:48]

    @staticmethod
    def _fallback_title(value: str) -> str:
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

    def _serialize_session_row(self, row) -> dict[str, str]:
        updated_at = str(row["updated_at"])
        return {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "group": _resolve_session_group(updated_at),
            "collectionId": str(row["collection"]),
            "updatedAt": updated_at,
        }

    @staticmethod
    def _serialize_message_row(row) -> dict[str, object]:
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
