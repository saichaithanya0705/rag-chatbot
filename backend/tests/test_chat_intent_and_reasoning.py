from __future__ import annotations

import asyncio
import unittest

from app.services.answer_trace import build_answer_trace
from app.services.ollama_client import OllamaGenerationResult
from app.services.rag_service import RagService, RetrievedChunk, RetrievedContext


class _ExplodingDocumentService:
    def count_indexed_chunks(self, *, user_id: str) -> int:
        raise AssertionError("Model-classified greeting should not inspect indexed PDF chunks.")


class _EmptyDocumentService:
    def count_indexed_chunks(self, *, user_id: str) -> int:
        return 0


class _FakeOllamaClient:
    def __init__(self, *, intent_response: str | None = None) -> None:
        self.intent_response = intent_response
        self.prompts: list[tuple[str, str]] = []

    async def generate_answer(self, prompt: str, system_prompt: str, *args, **kwargs) -> OllamaGenerationResult:
        self.prompts.append((prompt, system_prompt))
        if "classify the user's latest message" in system_prompt.lower():
            thinking = "I classified whether this was a greeting or a PDF question."
            return OllamaGenerationResult(
                response=self.intent_response
                or '{"intent":"knowledge","reply":null,"reason":"The user is asking a PDF question."}',
                thinking=thinking if kwargs.get("include_thinking") else None,
            )
        if "summarize model reasoning" in system_prompt.lower():
            if "hi! ask me anything from your pdfs." in prompt.lower():
                return OllamaGenerationResult(
                    response=(
                        "Reasoning summary\n\n"
                        "- Classified the message as a greeting.\n"
                        "- Skipped PDF retrieval because no PDF question was asked."
                    ),
                )
            return OllamaGenerationResult(
                response=(
                    "Reasoning summary\n\n"
                    "- Classified the request as a PDF question.\n"
                    "- Used the retrieved PDF evidence to answer with a citation."
                ),
            )
        return OllamaGenerationResult(
            response="A process is a program in execution. [SourceID: c1]",
            thinking="Use only the supplied evidence blocks. Internal prompt text.",
        )


def _service(
    *,
    ollama_client: _FakeOllamaClient | None = None,
    document_service: object | None = None,
) -> RagService:
    return RagService(
        ollama_client=ollama_client or _FakeOllamaClient(),  # type: ignore[arg-type]
        chroma_store=object(),  # type: ignore[arg-type]
        document_service=document_service or _ExplodingDocumentService(),  # type: ignore[arg-type]
        kg_manager=object(),  # type: ignore[arg-type]
        query_rewrite_service=object(),  # type: ignore[arg-type]
        reranker_service=object(),  # type: ignore[arg-type]
        web_search_service=object(),  # type: ignore[arg-type]
        top_k=3,
        web_search_score_threshold=0.3,
    )


def _context() -> RetrievedContext:
    return RetrievedContext(
        id="c1",
        kind="pdf",
        label="[SourceID: c1]",
        text="A process is a program in execution.",
        excerpt="A process is a program in execution.",
        document_id="d1",
        pdf_name="Operating System Notes.pdf",
        page_number=4,
        chunk_index=0,
    )


class ChatIntentAndReasoningTests(unittest.TestCase):
    def test_simple_greeting_uses_model_intent_before_pdf_retrieval(self) -> None:
        ollama_client = _FakeOllamaClient(
            intent_response='{"intent":"conversation","reply":"Hi! Ask me anything from your PDFs.","reason":"Greeting."}'
        )
        prepared = asyncio.run(_service(ollama_client=ollama_client).prepare_answer("hi", user_id="u1"))

        self.assertEqual(prepared.response_mode, "conversation")
        self.assertEqual(prepared.contexts, [])
        self.assertEqual(prepared.shortcut_answer, "Hi! Ask me anything from your PDFs.")
        self.assertTrue(
            any("classify the user's latest message" in system_prompt.lower() for _prompt, system_prompt in ollama_client.prompts)
        )

    def test_greeting_with_model_thinking_returns_greeting_summary(self) -> None:
        ollama_client = _FakeOllamaClient(
            intent_response='{"intent":"conversation","reply":"Hi! Ask me anything from your PDFs.","reason":"Greeting."}'
        )
        result = asyncio.run(
            _service(ollama_client=ollama_client).answer_question(
                "hi",
                thinking_enabled=True,
                user_id="u1",
            )
        )

        answer = result[0]
        model_thinking = result[6]
        response_mode = result[8]
        self.assertEqual(response_mode, "conversation")
        self.assertEqual(answer, "Hi! Ask me anything from your PDFs.")
        self.assertIn("- Classified the message as a greeting.", model_thinking or "")
        self.assertNotIn("Internal prompt", model_thinking or "")

    def test_greeting_plus_topic_follows_model_knowledge_classification(self) -> None:
        ollama_client = _FakeOllamaClient(
            intent_response='{"intent":"knowledge","reply":null,"reason":"Greeting plus a PDF topic question."}'
        )
        prepared = asyncio.run(
            _service(
                ollama_client=ollama_client,
                document_service=_EmptyDocumentService(),
            ).prepare_answer(
                "hi, what is deadlock in operating systems?",
                web_search_enabled=False,
                user_id="u1",
            )
        )

        self.assertEqual(prepared.response_mode, "grounded")
        self.assertNotEqual(prepared.shortcut_answer, "Hi! Ask me anything from your PDFs.")
        self.assertIn("PDFs", prepared.shortcut_answer or "")

    def test_conversation_trace_does_not_claim_pdf_grounding(self) -> None:
        trace = build_answer_trace(
            response_mode="conversation",
            conversation_detail="The model classified this as conversational, so PDF retrieval and web search were skipped.",
        )

        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0].kind, "conversation")
        self.assertNotIn("Scoped this answer", trace[0].detail)

    def test_think_blocks_are_removed_from_final_answer(self) -> None:
        answer, citations = _service(document_service=_EmptyDocumentService()).finalize_answer(
            "<think>Use only the supplied evidence blocks. Internal prompt text.</think>"
            "A process is a program in execution. [SourceID: c1]",
            [_context()],
        )

        self.assertEqual(answer, "A process is a program in execution.")
        self.assertEqual([citation.id for citation in citations], ["c1"])
        self.assertNotIn("Internal prompt", answer)

    def test_docling_source_metadata_flows_into_pdf_citation(self) -> None:
        context = _service()._pdf_context_from_chunk(
            RetrievedChunk(
                chunk_id="doc-1:1:0",
                collection_id="all_chunks",
                document_id="doc-1",
                pdf_name="Operating System Notes.pdf",
                page_number=1,
                chunk_index=0,
                text="Synthetic semantic chunk about a scheduling table.",
                parser="docling",
                content_labels=("section_header", "table"),
                source_text="| Algorithm | Behavior |\n| Round Robin | Cycles through ready queue |",
                source_refs=("#/tables/0",),
                source_blocks=(
                    {
                        "label": "table",
                        "page": 1,
                        "bbox": {"l": 20.0, "t": 90.0, "r": 500.0, "b": 180.0},
                        "source_ref": "#/tables/0",
                    },
                ),
                has_table=True,
            )
        )

        citation = RagService._citation_from_context(context).model_dump(by_alias=True)

        self.assertEqual(citation["parser"], "docling")
        self.assertEqual(citation["sourceLabels"], ["section_header", "table"])
        self.assertEqual(citation["sourceRefs"], ["#/tables/0"])
        self.assertEqual(citation["sourceText"], "| Algorithm | Behavior |\n| Round Robin | Cycles through ready queue |")
        self.assertEqual(citation["sourceLocation"], "section header + table")
        self.assertTrue(citation["hasTable"])
        self.assertEqual(citation["sourceBlocks"][0]["bbox"]["t"], 90.0)
        self.assertIn("Round Robin", citation["excerpt"])

    def test_model_thinking_on_returns_formatted_summary_not_raw_reasoning(self) -> None:
        ollama_client = _FakeOllamaClient()
        finalized = asyncio.run(
            _service(
                ollama_client=ollama_client,
                document_service=_EmptyDocumentService(),
            ).generate_finalized_answer(
                prepared=type(
                    "Prepared",
                    (),
                    {
                        "question": "What is a process?",
                        "prompt": "prompt",
                        "system_prompt": "system",
                        "contexts": [_context()],
                        "reasoning_segments": [],
                    },
                )(),
                thinking_enabled=True,
            )
        )

        self.assertEqual(finalized.answer, "A process is a program in execution.")
        self.assertEqual([citation.id for citation in finalized.citations], ["c1"])
        self.assertIsNotNone(finalized.model_thinking)
        self.assertIn("Reasoning summary", finalized.model_thinking or "")
        self.assertIn("- Used the retrieved PDF evidence", finalized.model_thinking or "")
        self.assertNotIn("Internal prompt", finalized.model_thinking or "")
        self.assertTrue(
            any("summarize model reasoning" in system_prompt.lower() for _prompt, system_prompt in ollama_client.prompts)
        )

    def test_model_thinking_off_returns_no_summary(self) -> None:
        ollama_client = _FakeOllamaClient()
        finalized = asyncio.run(
            _service(
                ollama_client=ollama_client,
                document_service=_EmptyDocumentService(),
            ).generate_finalized_answer(
                prepared=type(
                    "Prepared",
                    (),
                    {
                        "question": "What is a process?",
                        "prompt": "prompt",
                        "system_prompt": "system",
                        "contexts": [_context()],
                        "reasoning_segments": [],
                    },
                )(),
                thinking_enabled=False,
            )
        )

        self.assertEqual(finalized.answer, "A process is a program in execution.")
        self.assertIsNone(finalized.model_thinking)
        self.assertFalse(
            any("summarize model reasoning" in system_prompt.lower() for _prompt, system_prompt in ollama_client.prompts)
        )

    def test_model_thinking_summary_filters_prompt_leakage(self) -> None:
        cleaned = RagService._clean_model_thinking_summary(
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
