from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from app.core.database import Database
from app.services.kg_manager import TopicNodeRecord
from app.services.topic_index_service import SourceChunkRecord, TopicIndexService


class _FakeAllChunksCollection:
    def __init__(self, *, metadata_by_chunk_id: dict[str, dict[str, object]]) -> None:
        self._metadata_by_chunk_id = {
            chunk_id: dict(metadata)
            for chunk_id, metadata in metadata_by_chunk_id.items()
        }

    def get(
        self,
        *,
        ids: list[str] | None = None,
        include: list[str] | None = None,
        where: dict[str, object] | None = None,
    ) -> dict[str, list[object]]:
        del include, where
        selected_ids = ids if ids is not None else list(self._metadata_by_chunk_id)
        found_ids: list[str] = []
        metadatas: list[dict[str, object]] = []
        for chunk_id in selected_ids:
            metadata = self._metadata_by_chunk_id.get(chunk_id)
            if metadata is None:
                continue
            found_ids.append(chunk_id)
            metadatas.append(dict(metadata))
        return {
            "ids": found_ids,
            "metadatas": metadatas,
        }

    def update(self, *, ids: list[str], metadatas: list[dict[str, object]]) -> None:
        for chunk_id, metadata in zip(ids, metadatas, strict=False):
            self._metadata_by_chunk_id[str(chunk_id)] = dict(metadata)


class _FakeChromaStore:
    def __init__(self, *, collection: _FakeAllChunksCollection) -> None:
        self._collection = collection

    def collection(self, name: str) -> _FakeAllChunksCollection:
        if name != "all_chunks":
            raise KeyError(name)
        return self._collection


class _FailingKgManager:
    def rebuild(self, user_id: str, topics: list[TopicNodeRecord]) -> None:
        del user_id, topics
        raise RuntimeError("kg write failed")


class TopicProjectionConsistencyTests(unittest.TestCase):
    def test_projection_rolls_back_flat_metadata_and_sqlite_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "state.db")
            database.initialize()
            with database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO retrieval_chunks (
                        chunk_id,
                        document_id,
                        user_id,
                        pdf_name,
                        page_number,
                        chunk_index,
                        collection_id,
                        is_indexed,
                        text
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "doc-1:1:0",
                        "doc-1",
                        "user-a",
                        "doc-1.pdf",
                        1,
                        0,
                        "topic__old",
                        1,
                        "chunk text",
                    ),
                )

            collection = _FakeAllChunksCollection(
                metadata_by_chunk_id={
                    "doc-1:1:0": {
                        "document_id": "doc-1",
                        "user_id": "user-a",
                        "pdf_name": "doc-1.pdf",
                        "topic": "Old Topic",
                        "collection_id": "topic__old",
                    }
                }
            )
            service = TopicIndexService(
                chroma_store=_FakeChromaStore(collection=collection),  # type: ignore[arg-type]
                database=database,
                kg_manager=_FailingKgManager(),  # type: ignore[arg-type]
                topic_collection_prefix="topic__",
            )
            source_chunks = [
                SourceChunkRecord(
                    id="doc-1:1:0",
                    text="chunk text",
                    embedding=[0.1, 0.2, 0.3],
                    metadata={
                        "document_id": "doc-1",
                        "user_id": "user-a",
                        "pdf_name": "doc-1.pdf",
                        "topic": "Old Topic",
                        "collection_id": "topic__old",
                    },
                )
            ]
            topics = [
                TopicNodeRecord(
                    collection_id="topic__new",
                    display_name="New Topic",
                    centroid=[0.1, 0.2, 0.3],
                    chunk_ids=["doc-1:1:0"],
                    pdf_sources=["doc-1.pdf"],
                    keyword_summary=["new"],
                    page_keys=["doc-1.pdf:1"],
                )
            ]

            with self.assertRaises(RuntimeError):
                service._commit_topic_projection(
                    user_id="user-a",
                    source_chunks=source_chunks,
                    topics=topics,
                )

            restored = collection.get(ids=["doc-1:1:0"], include=["metadatas"])
            restored_metadata = dict(restored["metadatas"][0])
            self.assertEqual(restored_metadata.get("topic"), "Old Topic")
            self.assertEqual(restored_metadata.get("collection_id"), "topic__old")

            with database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT collection_id
                    FROM retrieval_chunks
                    WHERE chunk_id = ? AND user_id = ?
                    """,
                    ("doc-1:1:0", "user-a"),
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["collection_id"], "topic__old")

                journal_rows = connection.execute(
                    "SELECT COUNT(*) AS total FROM topic_projection_journal"
                ).fetchone()
                self.assertIsNotNone(journal_rows)
                self.assertEqual(int(journal_rows["total"]), 0)


if __name__ == "__main__":
    unittest.main()
