from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.rag_retrieval import RagRetrievalEngine


class _FakeCollection:
    def __init__(self) -> None:
        self.queries: list[dict[str, object]] = []
        self.metadata_by_id: dict[str, dict[str, object]] = {
            "topic-c1": {
                "document_id": "doc-1",
                "pdf_name": "OS.pdf",
                "page_number": 2,
                "chunk_index": 0,
                "collection_id": "topic-os",
                "user_id": "u1",
                "is_indexed": 1,
            },
            "qa-c1": {
                "parser": "docling",
                "content_labels": '["paragraph"]',
            },
        }

    def get(self, *, ids: list[str], include: list[str]) -> dict[str, object]:
        return {
            "ids": ids,
            "metadatas": [self.metadata_by_id.get(chunk_id, {}) for chunk_id in ids],
        }

    def query(self, **kwargs: object) -> dict[str, object]:
        self.queries.append(kwargs)
        return {
            "ids": [["topic-c1"]],
            "documents": [["Topic-scoped explanation of CPU scheduling."]],
            "metadatas": [[self.metadata_by_id["topic-c1"]]],
        }


class _FakeChromaStore:
    def __init__(self) -> None:
        self.collection_instance = _FakeCollection()

    def collection(self, name: str = "all_chunks") -> _FakeCollection:
        return self.collection_instance


class _FakeDocumentService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.rows_by_collection = {
            "all_chunks": [
                SimpleNamespace(
                    chunk_id="qa-c1",
                    collection_id="all_chunks",
                    document_id="doc-1",
                    pdf_name="OS.pdf",
                    page_number=1,
                    chunk_index=0,
                    text=(
                        "Question: What is process state in operating system?\n"
                        "Answer: A process state describes whether a process is ready, running, or waiting."
                    ),
                )
            ],
            "topic-os": [
                SimpleNamespace(
                    chunk_id="topic-c1",
                    collection_id="topic-os",
                    document_id="doc-1",
                    pdf_name="OS.pdf",
                    page_number=2,
                    chunk_index=0,
                    text="Topic-scoped explanation of CPU scheduling.",
                )
            ],
        }

    def search_chunk_catalog(
        self,
        *,
        query: str,
        collection_id: str,
        user_id: str,
        limit: int,
    ) -> list[SimpleNamespace]:
        self.calls.append(collection_id)
        return list(self.rows_by_collection.get(collection_id, []))

    def count_indexed_chunks(self, *, user_id: str) -> int:
        return 1


class _FakeKgManager:
    def has_topic(self, user_id: str, collection_id: str) -> bool:
        return collection_id == "topic-os"

    def rank_topics(self, user_id: str, query_embedding: list[float], top_n: int) -> list[object]:
        return []

    def expand_topics(
        self,
        user_id: str,
        seed_topics: list[object],
        *,
        limit: int,
        min_weight: float,
    ) -> list[str]:
        return []

    def topic_summaries(self, user_id: str) -> list[object]:
        return [SimpleNamespace(id="topic-os", chunk_count=1)]


class _FakeRerankerService:
    def score_pairs(self, query: str, passages: list[str]) -> list[float]:
        return [1.0 for _passage in passages]


def _engine(
    *,
    document_service: _FakeDocumentService | None = None,
    chroma_store: _FakeChromaStore | None = None,
) -> RagRetrievalEngine:
    return RagRetrievalEngine(
        chroma_store=chroma_store or _FakeChromaStore(),  # type: ignore[arg-type]
        document_service=document_service or _FakeDocumentService(),  # type: ignore[arg-type]
        kg_manager=_FakeKgManager(),  # type: ignore[arg-type]
        reranker_service=_FakeRerankerService(),  # type: ignore[arg-type]
        top_k=3,
        web_search_score_threshold=0.3,
    )


class RagRetrievalEngineTests(unittest.TestCase):
    def test_direct_lexical_shortcut_returns_grounded_context_and_answer(self) -> None:
        shortcut = _engine().direct_lexical_shortcut(
            "What is process state in operating system?",
            collection_id="all-pdfs",
            user_id="u1",
        )

        self.assertIsNotNone(shortcut)
        context, answer = shortcut or (None, "")
        self.assertEqual(context.id if context else None, "qa-c1")
        self.assertEqual(
            answer,
            "A process state describes whether a process is ready, running, or waiting.",
        )

    def test_specific_collection_retrieval_does_not_query_flat_collection(self) -> None:
        document_service = _FakeDocumentService()
        chroma_store = _FakeChromaStore()

        result = _engine(
            document_service=document_service,
            chroma_store=chroma_store,
        ).retrieve_chunks(
            "CPU scheduling",
            [0.1, 0.2],
            "topic-os",
            user_id="u1",
        )

        self.assertEqual([chunk.collection_id for chunk in result.chunks], ["topic-os"])
        self.assertNotIn("all_chunks", document_service.calls)
        self.assertEqual(
            chroma_store.collection_instance.queries[0]["where"],
            {"$and": [{"user_id": "u1"}, {"is_indexed": 1}, {"collection_id": "topic-os"}]},
        )


if __name__ == "__main__":
    unittest.main()
