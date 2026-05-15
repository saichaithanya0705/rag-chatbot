from __future__ import annotations

import unittest

from app.services.rag_answer_text import (
    clean_model_thinking_summary,
    derive_citations_from_answer,
    extract_direct_qa_pair,
    has_uncited_substantive_segments,
    references_unknown_sources,
    shape_shortcut_answer,
    strip_thinking_blocks,
)
from app.services.rag_types import RetrievedContext


def _pdf_context(
    context_id: str = "c1",
    *,
    text: str = "A process is a program in execution.",
    page_number: int = 4,
) -> RetrievedContext:
    return RetrievedContext(
        id=context_id,
        kind="pdf",
        label=f"[SourceID: {context_id}]",
        text=text,
        excerpt=text,
        document_id="d1",
        pdf_name="Operating System Notes.pdf",
        page_number=page_number,
        chunk_index=0,
    )


class RagAnswerTextTests(unittest.TestCase):
    def test_direct_qa_extraction_and_answer_shaping_are_module_boundaries(self) -> None:
        qa_pair = extract_direct_qa_pair(
            "Question: What is a process?\nAnswer: A process is a program in execution. It has state."
        )

        self.assertEqual(
            qa_pair,
            ("What is a process?", "A process is a program in execution. It has state."),
        )
        self.assertEqual(
            shape_shortcut_answer("Answer in one sentence: what is a process?", qa_pair[1]),
            "A process is a program in execution.",
        )

    def test_answer_safety_helpers_validate_known_sources_and_derivable_citations(self) -> None:
        contexts = [_pdf_context()]
        raw_answer = "<think>Internal prompt text.</think>A process is a program in execution. [SourceID: c1]"

        visible_answer = strip_thinking_blocks(raw_answer)
        self.assertNotIn("Internal prompt", visible_answer)
        self.assertFalse(references_unknown_sources(visible_answer, contexts))

        citations = derive_citations_from_answer("A process is a program in execution.", contexts)
        self.assertEqual([citation.id for citation in citations], ["c1"])
        self.assertFalse(
            has_uncited_substantive_segments("A process is a program in execution.", contexts)
        )
        self.assertTrue(references_unknown_sources("[SourceID: missing]", contexts))

    def test_model_thinking_summary_filters_prompt_leakage(self) -> None:
        cleaned = clean_model_thinking_summary(
            "Reasoning summary\n\n"
            "- Classified the message as a PDF question.\n"
            "- Internal prompt text: Use only the supplied evidence blocks.\n"
            "- Used retrieved evidence to answer."
        )

        self.assertIn("- Classified the message", cleaned or "")
        self.assertIn("- Used retrieved evidence", cleaned or "")
        self.assertNotIn("Internal prompt", cleaned or "")


if __name__ == "__main__":
    unittest.main()
