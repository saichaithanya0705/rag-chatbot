from __future__ import annotations

import unittest

from app.services.rag_prompting import build_prompt, focus_context_text, select_contexts
from app.services.rag_types import RetrievedContext


def _context(context_id: str, *, kind: str, text: str) -> RetrievedContext:
    return RetrievedContext(
        id=context_id,
        kind=kind,
        label=f"[{'Web' if kind == 'web' else 'SourceID'}: {context_id}]",
        text=text,
        excerpt=text[:80],
        title=f"{kind.title()} title",
        url=f"https://example.test/{context_id}" if kind == "web" else None,
    )


class RagPromptingTests(unittest.TestCase):
    def test_select_contexts_caps_pdf_and_web_blocks_by_prompt_budget(self) -> None:
        pdf_contexts = [_context(f"pdf-{index}", kind="pdf", text="PDF text") for index in range(5)]
        web_contexts = [_context(f"web-{index}", kind="web", text="Web text") for index in range(4)]

        selected = select_contexts(pdf_contexts, web_contexts, top_k=4)

        self.assertEqual([context.id for context in selected], ["pdf-0", "pdf-1", "pdf-2", "web-0", "web-1"])

    def test_focus_context_text_keeps_window_near_question_terms(self) -> None:
        text = "alpha " * 80 + "deadlock mutual exclusion circular wait " + "omega " * 80

        focused = focus_context_text(
            question="What are deadlock conditions?",
            text=text,
            max_chars=90,
        )

        self.assertIn("deadlock", focused)
        self.assertLessEqual(len(focused), 93)

    def test_build_prompt_renders_evidence_blocks_and_question_contract(self) -> None:
        prompt = build_prompt(
            question="What is deadlock?",
            contexts=[
                _context("c1", kind="pdf", text="Deadlock requires circular wait."),
                _context("https://example.test/deadlock", kind="web", text="Deadlock reference."),
            ],
            history_messages=[{"role": "user", "content": "Earlier question"}],
        )

        self.assertIn("PDF context:", prompt)
        self.assertIn("[SourceID: c1]", prompt)
        self.assertIn("Web search context:", prompt)
        self.assertIn("Question: What is deadlock?", prompt)
        self.assertIn("copy it exactly from the context", prompt)


if __name__ == "__main__":
    unittest.main()
