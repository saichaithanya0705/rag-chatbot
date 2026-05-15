from __future__ import annotations

import importlib
import unittest
from dataclasses import dataclass


@dataclass(frozen=True)
class _Context:
    kind: str
    text: str


def _grounding_module():
    try:
        return importlib.import_module("app.services.rag_grounding")
    except ModuleNotFoundError as error:
        if error.name == "app.services.rag_grounding":
            raise AssertionError("rag grounding helper module should exist") from error
        raise


def _extract_direct_qa_pair(text: str) -> tuple[str, str] | None:
    if text.startswith("Question:"):
        return "What is a process?", "A process is a program in execution."
    return None


class RagGroundingHelperTests(unittest.TestCase):
    def test_grounding_system_prompt_and_no_context_messages_keep_current_contract(self) -> None:
        grounding = _grounding_module()

        self.assertEqual(
            grounding.grounding_system_prompt(),
            (
                "Answer only from the supplied evidence blocks. "
                "Prefer PDF evidence when it directly answers the question. "
                "Use web evidence only to fill gaps or answer current facts the PDFs do not cover. "
                "If the evidence is insufficient, say so plainly. "
                "Grounded prose matters more than repeating source markers. "
                "If you include a source marker, copy it exactly from the evidence blocks. "
                "Do not invent, repair, or paraphrase source markers."
            ),
        )
        self.assertEqual(
            grounding.no_context_message(web_search_enabled=False, offline_warning=None),
            "I couldn't find enough support in your PDFs to answer that confidently.",
        )
        self.assertEqual(
            grounding.no_context_message(web_search_enabled=True, offline_warning=None),
            "I couldn't find enough relevant information in your PDFs or from web search to answer that confidently.",
        )
        self.assertEqual(
            grounding.no_context_message(web_search_enabled=True, offline_warning="Web search is offline."),
            "Web search is offline. Your PDFs do not contain enough information to answer that confidently.",
        )
        self.assertEqual(
            grounding.ungrounded_answer_message(),
            "I couldn't ground a confident answer in the retrieved sources.",
        )

    def test_fallback_answer_prefers_pdf_direct_qa_pair(self) -> None:
        grounding = _grounding_module()
        warning = "Used retrieved evidence fallback."
        web_context = _Context(kind="web", text="Question: What is a process?\nAnswer: Web copy.")
        pdf_context = _Context(kind="pdf", text="Question: What is a process?\nAnswer: A process is a program in execution.")

        fallback = grounding.compose_fallback_answer(
            [web_context, pdf_context],
            generation_warning=warning,
            extract_direct_qa_pair=_extract_direct_qa_pair,
        )

        self.assertEqual(fallback.answer, "A process is a program in execution.")
        self.assertEqual(fallback.citation_contexts, (pdf_context,))
        self.assertEqual(fallback.generation_warning, warning)

    def test_fallback_answer_uses_first_two_cleaned_passages_without_direct_qa(self) -> None:
        grounding = _grounding_module()
        first_context = _Context(kind="pdf", text="Page 4\nUseful process detail.\n\nCopyright 2026")
        second_context = _Context(kind="web", text="Additional scheduling detail.")
        third_context = _Context(kind="pdf", text="Ignored third passage.")

        fallback = grounding.compose_fallback_answer(
            [first_context, second_context, third_context],
            generation_warning="Used retrieved evidence fallback.",
            extract_direct_qa_pair=lambda _text: None,
        )

        self.assertEqual(fallback.answer, "Useful process detail.\n\nAdditional scheduling detail.")
        self.assertEqual(fallback.citation_contexts, (first_context, second_context))


if __name__ == "__main__":
    unittest.main()
