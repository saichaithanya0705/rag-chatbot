from __future__ import annotations

import unittest

from app.services.rag_comparison import (
    comparison_match_tokens,
    comparison_question_score,
    comparison_search_query,
    comparison_subqueries,
    comparison_token_variants,
)
from app.services.rag_types import CandidateChunk


class RagComparisonTests(unittest.TestCase):
    def test_comparison_subqueries_drop_prompt_instructions_and_short_fragments(self) -> None:
        self.assertEqual(
            comparison_subqueries(
                "Compare deadlock conditions and CPU scheduling in two short sentences based only on the PDF."
            ),
            ["deadlock conditions", "CPU scheduling"],
        )

    def test_comparison_search_query_and_tokens_reduce_generic_noise(self) -> None:
        self.assertEqual(comparison_search_query("Java classes"), "Java classes")
        self.assertEqual(comparison_search_query("round robin scheduling"), "round robin scheduling")
        self.assertIn("process", comparison_token_variants("processes"))
        self.assertEqual(
            comparison_match_tokens("Java classes and processes states", drop_generic=True),
            {"process", "processes", "state", "states"},
        )

    def test_comparison_question_score_prefers_matching_direct_qa_questions(self) -> None:
        candidate = CandidateChunk(
            chunk_id="c1",
            collection_id="all_chunks",
            document_id="d1",
            pdf_name="OS.pdf",
            page_number=1,
            chunk_index=0,
            text="Question: What are deadlock conditions?\nAnswer: Mutual exclusion and circular wait.",
        )

        self.assertGreater(comparison_question_score("deadlock conditions", candidate), 0.5)
        self.assertEqual(comparison_question_score("cpu scheduling", candidate), 0.0)


if __name__ == "__main__":
    unittest.main()
