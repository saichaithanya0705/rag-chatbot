from __future__ import annotations

import asyncio
import unittest

from app.services.rag.extractive_fallback_service import ExtractiveFallbackService
from app.services.rag.rag_types import RetrievedContext


def _context(context_id: str, text: str) -> RetrievedContext:
    return RetrievedContext(
        id=context_id,
        kind="pdf",
        label=f"notes.pdf, {context_id}",
        text=text,
        excerpt=text,
        document_id="doc-1",
        pdf_name="notes.pdf",
        page_number=1,
        chunk_index=0,
    )


class _SemanticEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed_texts_locally(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        embeddings: list[list[float]] = []
        for text in texts:
            if text == "What is a process?":
                embeddings.append([1.0, 0.0])
            elif "program in execution" in text:
                embeddings.append([0.98, 0.02])
            else:
                embeddings.append([0.0, 1.0])
        return embeddings


class _InvalidEmbedder:
    async def embed_texts_locally(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0]]


class _NonFiniteEmbedder:
    async def embed_texts_locally(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0], [float("nan"), 0.0]]


class _BlockingEmbedder:
    async def embed_texts_locally(self, texts: list[str]) -> list[list[float]]:
        await asyncio.Future()
        raise AssertionError("unreachable")


class ExtractiveFallbackServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_model_selects_the_best_cited_sentence(self) -> None:
        embedder = _SemanticEmbedder()
        service = ExtractiveFallbackService(embedder)

        result = await service.answer(
            "What is a process?",
            [
                _context("chunk-1", "Scheduling assigns CPU time to ready tasks."),
                _context(
                    "chunk-2",
                    "A thread is a unit of execution. A process is a program in execution.",
                ),
            ],
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.answer, "A process is a program in execution.")
        self.assertEqual(result.context.id, "chunk-2")
        self.assertGreater(result.score, 0.9)
        self.assertEqual(len(embedder.calls), 1)

    async def test_synthesis_question_skips_the_extractive_model(self) -> None:
        embedder = _SemanticEmbedder()
        service = ExtractiveFallbackService(embedder)

        result = await service.answer(
            "Compare processes and threads.",
            [_context("chunk-1", "A process contains one or more threads.")],
        )

        self.assertIsNone(result)
        self.assertEqual(embedder.calls, [])

    async def test_low_similarity_returns_no_ml_answer(self) -> None:
        service = ExtractiveFallbackService(_SemanticEmbedder(), minimum_score=0.5)

        result = await service.answer(
            "Which policy prevents starvation?",
            [_context("chunk-1", "A process is a program in execution.")],
        )

        self.assertIsNone(result)

    async def test_invalid_embedding_cardinality_is_rejected(self) -> None:
        service = ExtractiveFallbackService(_InvalidEmbedder())

        with self.assertRaisesRegex(ValueError, "expected"):
            await service.answer(
                "What is a process?",
                [_context("chunk-1", "A process is a program in execution.")],
            )

    async def test_non_finite_embedding_is_rejected(self) -> None:
        service = ExtractiveFallbackService(_NonFiniteEmbedder())

        with self.assertRaisesRegex(ValueError, "non-finite"):
            await service.answer(
                "What is a process?",
                [_context("chunk-1", "A process is a program in execution.")],
            )

    async def test_local_inference_has_a_hard_timeout(self) -> None:
        service = ExtractiveFallbackService(
            _BlockingEmbedder(),
            timeout_seconds=0.01,
        )

        with self.assertRaises(TimeoutError):
            await service.answer(
                "What is a process?",
                [_context("chunk-1", "A process is a program in execution.")],
            )

    def test_invalid_guardrail_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "minimum_score"):
            ExtractiveFallbackService(_SemanticEmbedder(), minimum_score=1.1)
        with self.assertRaisesRegex(ValueError, "timeout_seconds"):
            ExtractiveFallbackService(_SemanticEmbedder(), timeout_seconds=0.0)


if __name__ == "__main__":
    unittest.main()
