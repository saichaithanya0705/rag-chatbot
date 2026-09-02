from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from app.models.schemas import ChatRequest
from app.routers.chat import _stream_finalized_answer, stream_chat
from app.services.rag_service import RagService
from app.services.rag_types import PreparedAnswer, RetrievedContext


def _context() -> RetrievedContext:
    return RetrievedContext(
        id="chunk-1",
        kind="pdf",
        label="notes.pdf, page 1",
        text="A process is a program in execution.",
        excerpt="A process is a program in execution.",
        document_id="doc-1",
        pdf_name="notes.pdf",
        page_number=1,
        chunk_index=0,
    )


def _prepared(*, response_length: str = "standard") -> PreparedAnswer:
    return PreparedAnswer(
        question="What is a process?",
        prompt="prompt",
        system_prompt="system",
        contexts=[_context()],
        response_length=response_length,
    )


class _FailingGenerationClient:
    async def generate_answer(self, **_kwargs):
        raise httpx.ConnectError("provider unavailable")

    async def stream_answer(self, **_kwargs):
        if False:
            yield None
        raise httpx.ConnectError("provider unavailable")


class _InterruptedGenerationClient(_FailingGenerationClient):
    async def stream_answer(self, **_kwargs):
        yield SimpleNamespace(kind="response", content="Partial provider output")
        raise httpx.ReadError("provider stream interrupted")


class _TimeoutGenerationClient(_FailingGenerationClient):
    async def generate_answer(self, **_kwargs):
        raise TimeoutError("provider timed out")


class _UngroundedGenerationClient(_FailingGenerationClient):
    async def generate_answer(self, **_kwargs):
        return SimpleNamespace(response="Unsupported answer", thinking=None)


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


class ChatPipelineResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_generation_provider_failure_uses_grounded_evidence_fallback(self) -> None:
        service = object.__new__(RagService)
        service._nvidia_client = _FailingGenerationClient()

        finalized = await service.generate_finalized_answer(
            _prepared(),
            thinking_enabled=False,
        )

        self.assertEqual(finalized.answer, "A process is a program in execution.")
        self.assertEqual([citation.id for citation in finalized.citations], ["chunk-1"])
        self.assertIn("provider", (finalized.generation_warning or "").lower())

    async def test_stream_generation_provider_failure_uses_same_grounded_fallback(self) -> None:
        service = object.__new__(RagService)
        service._nvidia_client = _FailingGenerationClient()

        finalized = await _stream_finalized_answer(
            container=SimpleNamespace(
                nvidia_client=_FailingGenerationClient(),
                rag_service=service,
            ),
            prepared=_prepared(),
            thinking_enabled=False,
            http_request=_ConnectedRequest(),
        )

        self.assertEqual(finalized.answer, "A process is a program in execution.")
        self.assertEqual([citation.id for citation in finalized.citations], ["chunk-1"])
        self.assertIn("provider", (finalized.generation_warning or "").lower())

    async def test_interrupted_stream_discards_provider_result_in_final_grounded_answer(self) -> None:
        service = object.__new__(RagService)
        service._nvidia_client = _InterruptedGenerationClient()

        finalized = await _stream_finalized_answer(
            container=SimpleNamespace(
                nvidia_client=_InterruptedGenerationClient(),
                rag_service=service,
            ),
            prepared=_prepared(),
            thinking_enabled=False,
            http_request=_ConnectedRequest(),
        )

        self.assertEqual(finalized.answer, "A process is a program in execution.")
        self.assertNotIn("Partial provider output", finalized.answer)
        self.assertIn("interrupted", (finalized.generation_warning or "").lower())

    async def test_provider_failure_without_evidence_still_fails_closed(self) -> None:
        service = object.__new__(RagService)
        service._nvidia_client = _FailingGenerationClient()
        prepared = _prepared()
        prepared.contexts = []

        with self.assertRaises(httpx.ConnectError):
            await service.generate_finalized_answer(
                prepared,
                thinking_enabled=False,
            )

    async def test_stream_provider_failure_without_evidence_still_fails_closed(self) -> None:
        service = object.__new__(RagService)
        prepared = _prepared()
        prepared.contexts = []

        with self.assertRaises(httpx.ConnectError):
            await _stream_finalized_answer(
                container=SimpleNamespace(
                    nvidia_client=_FailingGenerationClient(),
                    rag_service=service,
                ),
                prepared=prepared,
                thinking_enabled=False,
                http_request=_ConnectedRequest(),
            )

    async def test_timeout_without_evidence_still_fails_closed(self) -> None:
        service = object.__new__(RagService)
        service._nvidia_client = _TimeoutGenerationClient()
        prepared = _prepared()
        prepared.contexts = []

        with self.assertRaises(TimeoutError):
            await service.generate_finalized_answer(
                prepared,
                thinking_enabled=False,
            )

    async def test_ungrounded_sync_generation_uses_evidence_fallback(self) -> None:
        service = object.__new__(RagService)
        service._nvidia_client = _UngroundedGenerationClient()

        finalized = await service.generate_finalized_answer(
            _prepared(),
            thinking_enabled=False,
        )

        self.assertEqual(finalized.answer, "A process is a program in execution.")
        self.assertEqual([citation.id for citation in finalized.citations], ["chunk-1"])
        self.assertIn("ground", (finalized.generation_warning or "").lower())

    def test_completed_ungrounded_stream_uses_grounded_evidence_fallback(self) -> None:
        service = object.__new__(RagService)

        finalized = service.finalize_streamed_answer("", [_context()])

        self.assertEqual(finalized.answer, "A process is a program in execution.")
        self.assertEqual([citation.id for citation in finalized.citations], ["chunk-1"])

    async def test_stream_route_propagates_comprehensive_response_length(self) -> None:
        captured: dict[str, object] = {}

        class _HistoryService:
            async def get_hybrid_memory(self, **_kwargs):
                return [], 0

        class _RagService:
            async def prepare_answer(self, question: str, **kwargs):
                captured["question"] = question
                captured.update(kwargs)
                prepared = _prepared(response_length=str(kwargs["response_length"]))
                prepared.shortcut_answer = "Grounded shortcut."
                prepared.shortcut_citations = []
                return prepared

            async def summarize_model_thinking(self, *_args, **_kwargs):
                return None

        container = SimpleNamespace(
            history_service=_HistoryService(),
            rag_service=_RagService(),
            nvidia_client=SimpleNamespace(),
        )
        request = ChatRequest(
            message="Explain this in detail",
            collectionId="all-pdfs",
            webSearchEnabled=False,
            responseLength="comprehensive",
        )

        with (
            patch("app.routers.chat._enforce_chat_rate_limit"),
            patch("app.routers.chat._topic_exists", return_value=True),
            patch("app.routers.chat._resolve_collection_label", return_value="All PDFs"),
        ):
            response = await stream_chat(
                request,
                _ConnectedRequest(),
                container=container,
                user_id="user-1",
            )
            async for _chunk in response.body_iterator:
                pass

        self.assertEqual(captured["response_length"], "comprehensive")

    async def test_stream_route_finishes_with_cited_fallback_when_provider_fails(self) -> None:
        async def prepare_answer(_question: str, **_kwargs):
            return _prepared()

        service = object.__new__(RagService)
        service._nvidia_client = _FailingGenerationClient()
        service.prepare_answer = prepare_answer

        class _HistoryService:
            async def get_hybrid_memory(self, **_kwargs):
                return [], 0

        container = SimpleNamespace(
            history_service=_HistoryService(),
            rag_service=service,
            nvidia_client=_FailingGenerationClient(),
        )
        request = ChatRequest(
            message="What is a process?",
            collectionId="all-pdfs",
            webSearchEnabled=False,
        )

        with (
            patch("app.routers.chat._enforce_chat_rate_limit"),
            patch("app.routers.chat._topic_exists", return_value=True),
            patch("app.routers.chat._resolve_collection_label", return_value="All PDFs"),
        ):
            response = await stream_chat(
                request,
                _ConnectedRequest(),
                container=container,
                user_id="user-1",
            )
            events = [chunk async for chunk in response.body_iterator]

        payload = "".join(str(event) for event in events)
        self.assertIn('"type": "done"', payload)
        self.assertIn('"id": "chunk-1"', payload)
        self.assertNotIn('"type": "error"', payload)


if __name__ == "__main__":
    unittest.main()
