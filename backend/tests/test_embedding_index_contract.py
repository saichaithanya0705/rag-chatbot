from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.database import Database
from app.services.embedding_index_service import EmbeddingIndexService


class _FakeChromaStore:
    def __init__(self, *, has_collections: bool = False) -> None:
        self._has_collections = has_collections
        self.reset_calls = 0

    def has_collections(self) -> bool:
        return self._has_collections

    def reset(self) -> None:
        self.reset_calls += 1
        self._has_collections = False


class EmbeddingIndexContractTests(unittest.TestCase):
    def test_empty_store_records_current_embedding_contract_without_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "state.db")
            database.initialize()
            chroma_store = _FakeChromaStore()

            EmbeddingIndexService(
                database=database,
                chroma_store=chroma_store,  # type: ignore[arg-type]
                kg_path=Path(temp_dir) / "kg.pkl",
                model="all-minilm",
                dimensions=384,
            ).reconcile()

            state = database.get_embedding_index_state()
            self.assertIsNotNone(state)
            self.assertEqual(state.model if state else None, "all-minilm")
            self.assertEqual(state.dimensions if state else None, 384)
            self.assertEqual(chroma_store.reset_calls, 0)

    def test_model_change_resets_vector_backed_state_and_marks_documents_for_reindex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "state.db")
            database.initialize()
            database.set_embedding_index_state(
                model="andersc/qwen3-embedding:0.6b",
                dimensions=1024,
            )

            with database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO ingested_documents (
                        id,
                        user_id,
                        pdf_name,
                        source_path,
                        page_count,
                        chunk_count,
                        status,
                        progress,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "doc-1",
                        "user-a",
                        "doc-1.pdf",
                        str(Path(temp_dir) / "doc-1.pdf"),
                        2,
                        3,
                        "indexed",
                        100,
                        "2026-05-21T00:00:00+00:00",
                        "2026-05-21T00:00:00+00:00",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO ingested_pages (document_id, page_number, content)
                    VALUES (?, ?, ?)
                    """,
                    ("doc-1", 1, "page text"),
                )
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

            kg_path = Path(temp_dir) / "kg.pkl"
            kg_json_path = kg_path.with_suffix(".json")
            kg_json_path.write_text("{}", encoding="utf-8")
            chroma_store = _FakeChromaStore(has_collections=True)

            EmbeddingIndexService(
                database=database,
                chroma_store=chroma_store,  # type: ignore[arg-type]
                kg_path=kg_path,
                model="all-minilm",
                dimensions=384,
            ).reconcile()

            self.assertEqual(chroma_store.reset_calls, 1)
            self.assertFalse(kg_json_path.exists())

            state = database.get_embedding_index_state()
            self.assertIsNotNone(state)
            self.assertEqual(state.model if state else None, "all-minilm")
            self.assertEqual(state.dimensions if state else None, 384)

            with database.connect() as connection:
                chunk_count = connection.execute(
                    "SELECT COUNT(*) AS total FROM retrieval_chunks"
                ).fetchone()
                page_count = connection.execute(
                    "SELECT COUNT(*) AS total FROM ingested_pages"
                ).fetchone()
                document = connection.execute(
                    """
                    SELECT status, progress, page_count, chunk_count
                    FROM ingested_documents
                    WHERE id = ?
                    """,
                    ("doc-1",),
                ).fetchone()

            self.assertEqual(int(chunk_count["total"]), 0)
            self.assertEqual(int(page_count["total"]), 0)
            self.assertEqual(document["status"], "queued")
            self.assertEqual(int(document["progress"]), 0)
            self.assertEqual(int(document["page_count"]), 0)
            self.assertEqual(int(document["chunk_count"]), 0)


if __name__ == "__main__":
    unittest.main()
