from __future__ import annotations

import asyncio
import importlib
from unittest.mock import AsyncMock, MagicMock

from app.core.chroma_store import ChromaStore
from app.services import _LEGACY_MODULE_MAP
from app.services.chat.query_rewrite_service import QueryRewriteService
from app.services.documents.document_service import DocumentService
from app.services.knowledge.kg_manager import KgManager
from app.services.providers.nvidia_client import NvidiaClient
from app.services.providers.reranker_service import RerankerService
from app.services.providers.web_search_service import WebSearchService
from app.services.rag.extractive_fallback_service import (
    ExtractiveFallbackResult,
    ExtractiveFallbackService,
)
from app.services.rag.rag_service import RagService
from app.services.rag.rag_types import RetrievedContext


def test_legacy_service_module_aliases_resolve_to_canonical_modules() -> None:
    for legacy_name, canonical_name in _LEGACY_MODULE_MAP.items():
        legacy_module = importlib.import_module(legacy_name)
        canonical_module = importlib.import_module(canonical_name)

        assert legacy_module.__name__ == legacy_name
        assert legacy_module.__spec__ is not None
        assert legacy_module.__spec__.name == legacy_name
        for public_name in legacy_module.__all__:
            assert getattr(legacy_module, public_name) is getattr(canonical_module, public_name)


def test_rag_service_uses_injected_extractive_fallback() -> None:
    context = RetrievedContext(
        id="chunk-1",
        kind="pdf",
        label="processes.pdf, page 1",
        text="A process is a program in execution.",
        excerpt="A process is a program in execution.",
        document_id="doc-1",
        pdf_name="processes.pdf",
        page_number=1,
        chunk_index=0,
    )
    extractive_fallback = MagicMock(spec=ExtractiveFallbackService)
    extractive_fallback.answer = AsyncMock(
        return_value=ExtractiveFallbackResult(
            answer="A process is a program in execution.",
            context=context,
            score=0.93,
        )
    )

    service = RagService(
        nvidia_client=MagicMock(spec=NvidiaClient),
        chroma_store=MagicMock(spec=ChromaStore),
        document_service=MagicMock(spec=DocumentService),
        kg_manager=MagicMock(spec=KgManager),
        query_rewrite_service=MagicMock(spec=QueryRewriteService),
        reranker_service=MagicMock(spec=RerankerService),
        web_search_service=MagicMock(spec=WebSearchService),
        extractive_fallback_service=extractive_fallback,
        top_k=3,
        web_search_score_threshold=0.3,
    )

    finalized = asyncio.run(
        service.resolve_generation_fallback(
            "What is a process?",
            [context],
            reason="provider_unavailable",
        )
    )

    extractive_fallback.answer.assert_awaited_once_with("What is a process?", [context])
    assert finalized.answer == "A process is a program in execution."
    assert [citation.id for citation in finalized.citations] == ["chunk-1"]
