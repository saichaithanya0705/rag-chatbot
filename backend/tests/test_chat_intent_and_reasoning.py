from __future__ import annotations

import asyncio
import unittest

from app.services.answer_trace import build_answer_trace
from app.services.nvidia_client import NvidiaGenerationResult
from app.services.rag_answer_text import clean_model_thinking_summary
from app.services.rag_citations import citation_from_context, pdf_context_from_chunk
from app.services.rag_service import RagService
from app.services.rag_types import RetrievedChunk, RetrievedContext
from app.services.web_search_service import WebSearchResult


class _ExplodingDocumentService:
    def count_indexed_chunks(self, *, user_id: str) -> int:
        raise AssertionError("Model-classified greeting should not inspect indexed PDF chunks.")

    def list_documents(self, *, user_id: str) -> list[dict[str, object]]:
        raise AssertionError("Model-classified greeting should not inspect the document inventory.")


class _EmptyDocumentService:
    def count_indexed_chunks(self, *, user_id: str) -> int:
        return 0

    def list_documents(self, *, user_id: str) -> list[dict[str, object]]:
        return []

    def search_chunk_catalog(
        self,
        *,
        query: str,
        collection_id: str,
        user_id: str,
        limit: int,
    ) -> list[object]:
        return []


class _InventoryDocumentService:
    def __init__(self) -> None:
        self.requested_user_ids: list[str] = []

    def count_indexed_chunks(self, *, user_id: str) -> int:
        raise AssertionError("Document inventory answers should not inspect indexed PDF chunks.")

    def list_documents(self, *, user_id: str) -> list[dict[str, object]]:
        self.requested_user_ids.append(user_id)
        return [
            {
                "id": "doc-1",
                "pdf_name": "Operating System Notes.pdf",
                "page_count": 12,
                "chunk_count": 34,
                "status": "indexed",
                "progress": 100,
            },
            {
                "id": "doc-2",
                "pdf_name": "Surgery Notes.pdf",
                "page_count": 0,
                "chunk_count": 0,
                "status": "embedding",
                "progress": 70,
            },
        ]


class _FakeNvidiaClient:
    def __init__(self, *, intent_response: str | None = None) -> None:
        self.intent_response = intent_response
        self.prompts: list[tuple[str, str]] = []

    async def generate_answer(self, prompt: str, system_prompt: str, *args, **kwargs) -> NvidiaGenerationResult:
        self.prompts.append((prompt, system_prompt))
        if "classify the user's latest message" in system_prompt.lower():
            thinking = "I classified whether this was a greeting or a PDF question."
            return NvidiaGenerationResult(
                response=self.intent_response
                or '{"intent":"knowledge","confidence":0.91,"reply":null,"reason":"The user is asking a PDF question."}',
                thinking=thinking if kwargs.get("include_thinking") else None,
            )
        if "summarize model reasoning" in system_prompt.lower():
            if "hi! ask me anything from your pdfs." in prompt.lower():
                return NvidiaGenerationResult(
                    response=(
                        "Reasoning summary\n\n"
                        "- Classified the message as a greeting.\n"
                        "- Skipped PDF retrieval because no PDF question was asked."
                    ),
                )
            return NvidiaGenerationResult(
                response=(
                    "Reasoning summary\n\n"
                    "- Classified the request as a PDF question.\n"
                    "- Used the retrieved PDF evidence to answer with a citation."
                ),
            )
        return NvidiaGenerationResult(
            response="A process is a program in execution. [SourceID: c1]",
            thinking="Use only the supplied evidence blocks. Internal prompt text.",
        )


class _FakeRerankerService:
    def score_pairs(self, query: str, passages: list[str]) -> list[float]:
        return [1.0 for _passage in passages]


class _FakeWebSearchService:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str) -> list[WebSearchResult]:
        self.queries.append(query)
        return [
            WebSearchResult(
                title="OpenAI News",
                url="https://openai.com/news/",
                snippet="Latest updates from OpenAI.",
                content="Latest updates from OpenAI about current model and product releases.",
            )
        ]


def _service(
    *,
    nvidia_client: _FakeNvidiaClient | None = None,
    document_service: object | None = None,
    reranker_service: object | None = None,
    web_search_service: object | None = None,
) -> RagService:
    return RagService(
        nvidia_client=nvidia_client or _FakeNvidiaClient(),  # type: ignore[arg-type]
        chroma_store=object(),  # type: ignore[arg-type]
        document_service=document_service or _ExplodingDocumentService(),  # type: ignore[arg-type]
        kg_manager=object(),  # type: ignore[arg-type]
        query_rewrite_service=object(),  # type: ignore[arg-type]
        reranker_service=reranker_service or object(),  # type: ignore[arg-type]
        web_search_service=web_search_service or object(),  # type: ignore[arg-type]
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
        nvidia_client = _FakeNvidiaClient(
            intent_response='{"intent":"conversation","confidence":0.98,"reply":"Hi! Ask me anything from your PDFs.","reason":"Greeting."}'
        )
        prepared = asyncio.run(_service(nvidia_client=nvidia_client).prepare_answer("hi", user_id="u1"))

        self.assertEqual(prepared.response_mode, "conversation")
        self.assertEqual(prepared.contexts, [])
        self.assertEqual(prepared.shortcut_answer, "Hi! Ask me anything from your PDFs.")
        self.assertTrue(
            any("classify the user's latest message" in system_prompt.lower() for _prompt, system_prompt in nvidia_client.prompts)
        )

    def test_assistant_meta_question_is_conversation_without_pdf_retrieval(self) -> None:
        nvidia_client = _FakeNvidiaClient()
        prepared = asyncio.run(
            _service(nvidia_client=nvidia_client).prepare_answer("what can you do?", user_id="u1")
        )

        self.assertEqual(prepared.response_mode, "conversation")
        self.assertEqual(prepared.contexts, [])
        self.assertIn("local RAG chat assistant", prepared.shortcut_answer or "")
        self.assertEqual(nvidia_client.prompts, [])

    def test_domain_use_question_does_not_match_app_help_shortcut(self) -> None:
        nvidia_client = _FakeNvidiaClient()
        prepared = asyncio.run(
            _service(
                nvidia_client=nvidia_client,
                document_service=_EmptyDocumentService(),
            ).prepare_answer(
                "how do I use insulin from this PDF?",
                web_search_enabled=False,
                user_id="u1",
            )
        )

        self.assertEqual(prepared.response_mode, "grounded")
        self.assertNotIn("local RAG chat assistant", prepared.shortcut_answer or "")
        self.assertTrue(
            any("classify the user's latest message" in system_prompt.lower() for _prompt, system_prompt in nvidia_client.prompts)
        )

    def test_classifier_prompt_includes_recent_chat_context_for_ambiguous_followup(self) -> None:
        nvidia_client = _FakeNvidiaClient(
            intent_response='{"intent":"conversation","confidence":0.86,"reply":"Sure - I can walk you through that.","reason":"The latest message agrees to prior app-help guidance."}'
        )
        prepared = asyncio.run(
            _service(nvidia_client=nvidia_client).prepare_answer(
                "yes please",
                history_messages=[
                    {"role": "user", "content": "How do I use this app?"},
                    {"role": "assistant", "content": "I can explain how uploads and PDF questions work."},
                ],
                user_id="u1",
            )
        )

        prompt, _system_prompt = nvidia_client.prompts[0]
        self.assertEqual(prepared.response_mode, "conversation")
        self.assertIn("Recent conversation context", prompt)
        self.assertIn("user: How do I use this app?", prompt)
        self.assertIn("assistant: I can explain how uploads and PDF questions work.", prompt)
        self.assertIn("Latest user message:\nyes please", prompt)

    def test_context_aware_classifier_can_route_inventory_followup(self) -> None:
        nvidia_client = _FakeNvidiaClient(
            intent_response='{"intent":"document_inventory","confidence":0.84,"reply":null,"reason":"The user is accepting a prior offer to list PDFs."}'
        )
        document_service = _InventoryDocumentService()
        prepared = asyncio.run(
            _service(
                nvidia_client=nvidia_client,
                document_service=document_service,
            ).prepare_answer(
                "yes, show them",
                history_messages=[
                    {"role": "user", "content": "Can you tell me what PDFs are available?"},
                    {"role": "assistant", "content": "I can list the PDFs available in this workspace."},
                ],
                user_id="u1",
            )
        )

        self.assertEqual(prepared.response_mode, "document_inventory")
        self.assertEqual(document_service.requested_user_ids, ["u1"])
        self.assertIn("Operating System Notes.pdf", prepared.shortcut_answer or "")

    def test_low_confidence_model_intent_falls_back_to_knowledge(self) -> None:
        nvidia_client = _FakeNvidiaClient(
            intent_response='{"intent":"conversation","confidence":0.32,"reply":"Sure.","reason":"Ambiguous follow-up."}'
        )
        prepared = asyncio.run(
            _service(
                nvidia_client=nvidia_client,
                document_service=_EmptyDocumentService(),
            ).prepare_answer(
                "what about that?",
                web_search_enabled=False,
                user_id="u1",
            )
        )

        self.assertEqual(prepared.response_mode, "grounded")
        self.assertIn("PDFs", prepared.shortcut_answer or "")

    def test_document_inventory_request_lists_workspace_pdfs_without_retrieval(self) -> None:
        nvidia_client = _FakeNvidiaClient()
        document_service = _InventoryDocumentService()
        prepared = asyncio.run(
            _service(
                nvidia_client=nvidia_client,
                document_service=document_service,
            ).prepare_answer(
                "what pdfs do u have access to now",
                user_id="u1",
            )
        )

        self.assertEqual(prepared.response_mode, "document_inventory")
        self.assertEqual(prepared.contexts, [])
        self.assertIsNone(prepared.tool_call)
        self.assertFalse(prepared.web_search_used)
        self.assertEqual(document_service.requested_user_ids, ["u1"])
        self.assertEqual(nvidia_client.prompts, [])
        self.assertIn("Operating System Notes.pdf - indexed; 12 pages; 34 chunks.", prepared.shortcut_answer or "")
        self.assertIn("Surgery Notes.pdf - embedding (70%); not ready", prepared.shortcut_answer or "")

    def test_greeting_with_model_thinking_returns_greeting_summary(self) -> None:
        nvidia_client = _FakeNvidiaClient(
            intent_response='{"intent":"conversation","confidence":0.98,"reply":"Hi! Ask me anything from your PDFs.","reason":"Greeting."}'
        )
        result = asyncio.run(
            _service(nvidia_client=nvidia_client).answer_question(
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
        nvidia_client = _FakeNvidiaClient(
            intent_response='{"intent":"knowledge","confidence":0.93,"reply":null,"reason":"Greeting plus a PDF topic question."}'
        )
        prepared = asyncio.run(
            _service(
                nvidia_client=nvidia_client,
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

    def test_web_search_enabled_uses_web_when_pdf_context_is_empty(self) -> None:
        web_search_service = _FakeWebSearchService()
        prepared = asyncio.run(
            _service(
                document_service=_EmptyDocumentService(),
                reranker_service=_FakeRerankerService(),
                web_search_service=web_search_service,
            ).prepare_answer(
                "what is the latest OpenAI news?",
                web_search_enabled=True,
                user_id="u1",
            )
        )

        self.assertEqual(web_search_service.queries, ["what is the latest OpenAI news?"])
        self.assertIsNotNone(prepared.tool_call)
        self.assertTrue(prepared.web_search_used)
        self.assertEqual([context.kind for context in prepared.contexts], ["web"])
        self.assertIn("OpenAI News", prepared.contexts[0].text)

    def test_conversation_trace_does_not_claim_pdf_grounding(self) -> None:
        trace = build_answer_trace(
            response_mode="conversation",
            conversation_detail="The model classified this as conversational, so PDF retrieval and web search were skipped.",
        )

        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0].kind, "conversation")
        self.assertNotIn("Scoped this answer", trace[0].detail)

    def test_document_inventory_trace_does_not_claim_pdf_grounding(self) -> None:
        trace = build_answer_trace(
            response_mode="document_inventory",
            conversation_detail="Recognized this as a document inventory request, so PDF retrieval and web search were skipped.",
        )

        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0].kind, "inventory")
        self.assertIn("document inventory", trace[0].detail)
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

    def test_parser_source_metadata_flows_into_pdf_citation(self) -> None:
        context = pdf_context_from_chunk(
            RetrievedChunk(
                chunk_id="doc-1:1:0",
                collection_id="all_chunks",
                document_id="doc-1",
                pdf_name="Operating System Notes.pdf",
                page_number=1,
                chunk_index=0,
                text="Synthetic semantic chunk about a scheduling table.",
                parser="opendataloader_pdf",
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

        citation = citation_from_context(context).model_dump(by_alias=True)

        self.assertEqual(citation["parser"], "opendataloader_pdf")
        self.assertEqual(citation["sourceLabels"], ["section_header", "table"])
        self.assertEqual(citation["sourceRefs"], ["#/tables/0"])
        self.assertEqual(citation["sourceText"], "| Algorithm | Behavior |\n| Round Robin | Cycles through ready queue |")
        self.assertEqual(citation["sourceLocation"], "section header + table")
        self.assertTrue(citation["hasTable"])
        self.assertEqual(citation["sourceBlocks"][0]["bbox"]["t"], 90.0)
        self.assertIn("Round Robin", citation["excerpt"])

    def test_model_thinking_on_returns_formatted_summary_not_raw_reasoning(self) -> None:
        nvidia_client = _FakeNvidiaClient()
        finalized = asyncio.run(
            _service(
                nvidia_client=nvidia_client,
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
                        "images": [],
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
            any("summarize model reasoning" in system_prompt.lower() for _prompt, system_prompt in nvidia_client.prompts)
        )

    def test_model_thinking_off_returns_no_summary(self) -> None:
        nvidia_client = _FakeNvidiaClient()
        finalized = asyncio.run(
            _service(
                nvidia_client=nvidia_client,
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
                        "images": [],
                    },
                )(),
                thinking_enabled=False,
            )
        )

        self.assertEqual(finalized.answer, "A process is a program in execution.")
        self.assertIsNone(finalized.model_thinking)
        self.assertFalse(
            any("summarize model reasoning" in system_prompt.lower() for _prompt, system_prompt in nvidia_client.prompts)
        )

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
