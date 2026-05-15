from __future__ import annotations

import unittest

from app.services.rag_retrieval_policy import (
    build_fts_query,
    rerank_pool_limit,
    rrf_score,
    select_final_chunks,
    select_rerank_candidate_pool,
    should_query_flat_collection,
    should_rerank_candidates,
)
from app.services.rag_types import CandidateChunk


def _candidate(
    chunk_id: str,
    *,
    document_id: str | None = None,
    collection_id: str | None = None,
    fused_score: float = 0.0,
) -> CandidateChunk:
    return CandidateChunk(
        chunk_id=chunk_id,
        collection_id=collection_id or f"collection-{chunk_id}",
        document_id=document_id or f"document-{chunk_id}",
        pdf_name=f"{chunk_id}.pdf",
        page_number=1,
        chunk_index=0,
        text=f"Chunk {chunk_id}",
        fused_score=fused_score,
    )


class RagRetrievalPolicyTests(unittest.TestCase):
    def test_build_fts_query_deduplicates_tokens_in_query_order(self) -> None:
        self.assertEqual(
            build_fts_query("CPU scheduling, cpu scheduling states"),
            '"cpu" OR "scheduling" OR "states"',
        )

    def test_flat_collection_policy_only_broadens_sparse_all_pdf_topic_results(self) -> None:
        self.assertFalse(
            should_query_flat_collection(
                collection_id="topic-os",
                target_collections=["topic-os"],
                candidate_count=0,
                collection_name="all_chunks",
                top_k=3,
            )
        )
        self.assertFalse(
            should_query_flat_collection(
                collection_id="all-pdfs",
                target_collections=["all_chunks"],
                candidate_count=0,
                collection_name="all_chunks",
                top_k=3,
            )
        )
        self.assertTrue(
            should_query_flat_collection(
                collection_id="all-pdfs",
                target_collections=[],
                candidate_count=0,
                collection_name="all_chunks",
                top_k=3,
            )
        )
        self.assertTrue(
            should_query_flat_collection(
                collection_id="all-pdfs",
                target_collections=["topic-os"],
                candidate_count=2,
                collection_name="all_chunks",
                top_k=3,
            )
        )

    def test_rerank_pool_keeps_comparison_questions_wide(self) -> None:
        candidates = [_candidate(str(index)) for index in range(12)]

        self.assertEqual(
            rerank_pool_limit(
                question="What is CPU scheduling?",
                ordered_candidates=candidates,
                top_k=3,
            ),
            6,
        )
        self.assertEqual(
            rerank_pool_limit(
                question="Compare CPU scheduling and memory paging",
                ordered_candidates=candidates,
                top_k=3,
            ),
            8,
        )

    def test_rerank_pool_adds_missing_comparison_coverage_groups(self) -> None:
        candidates = [_candidate(f"c{index}") for index in range(1, 5)]

        selected = select_rerank_candidate_pool(
            ordered_candidates=candidates,
            coverage_groups=[{"c4"}],
            limit=2,
        )

        self.assertEqual([candidate.chunk_id for candidate in selected], ["c1", "c2", "c4"])

    def test_final_selection_prioritizes_comparison_coverage_before_fill(self) -> None:
        candidates = [_candidate(f"c{index}") for index in range(1, 5)]

        selected = select_final_chunks(
            ranked_candidates=candidates,
            coverage_groups=[{"c3"}, {"c2"}],
            top_k=3,
        )

        self.assertEqual([candidate.chunk_id for candidate in selected], ["c3", "c2", "c1"])

    def test_rerank_decision_skips_clear_dominant_rankings(self) -> None:
        candidates = [
            _candidate(
                "c1",
                document_id="doc-1",
                collection_id="topic-a",
                fused_score=rrf_score(0),
            ),
            _candidate(
                "c2",
                document_id="doc-1",
                collection_id="topic-a",
                fused_score=rrf_score(1),
            ),
            _candidate(
                "c3",
                document_id="doc-1",
                collection_id="topic-a",
                fused_score=rrf_score(2),
            ),
            _candidate(
                "c4",
                document_id="doc-1",
                collection_id="topic-a",
                fused_score=rrf_score(3),
            ),
        ]

        self.assertFalse(
            should_rerank_candidates(
                question="What is CPU scheduling?",
                ordered_candidates=candidates,
                top_k=3,
            )
        )

    def test_rerank_decision_keeps_comparison_queries_rerankable(self) -> None:
        candidates = [
            _candidate(
                "c1",
                document_id="doc-1",
                collection_id="topic-a",
                fused_score=rrf_score(0),
            ),
            _candidate(
                "c2",
                document_id="doc-1",
                collection_id="topic-a",
                fused_score=rrf_score(1),
            ),
        ]

        self.assertTrue(
            should_rerank_candidates(
                question="Compare CPU scheduling and memory paging",
                ordered_candidates=candidates,
                top_k=3,
            )
        )


if __name__ == "__main__":
    unittest.main()
