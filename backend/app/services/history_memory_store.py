from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class MemoryTurn:
    user_content: str
    assistant_content: str
    session_id: str
    collection_id: str


class HistoryMemoryStore:
    def __init__(
        self,
        *,
        collection_getter: Callable[[], Any],
        cross_session_memory_enabled: bool,
    ) -> None:
        self._collection_getter = collection_getter
        self._cross_session_memory_enabled = cross_session_memory_enabled

    def query_turns_by_embedding(
        self,
        *,
        query_embedding: list[float],
        session_id: str | None,
        collection_id: str,
        user_id: str,
        limit: int,
    ) -> list[MemoryTurn]:
        collection = self._collection_getter()
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

    def get_stats(self, *, user_id: str) -> dict[str, object]:
        rows = self._collection_getter().get(where={"user_id": user_id}, include=["metadatas"])
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

    def upsert_turn(
        self,
        *,
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
        self._collection_getter().upsert(
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

    def delete_turn(self, memory_id: str) -> None:
        self._collection_getter().delete(ids=[memory_id])
