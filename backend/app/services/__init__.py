"""Service layer organized by domain: chat, documents, history, ingestion, knowledge, providers, and rag."""

from __future__ import annotations

import importlib
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
import sys
from types import ModuleType
from typing import Any

_LEGACY_MODULE_MAP = {
    "app.services.answer_trace": "app.services.chat.answer_trace",
    "app.services.chat_rate_limiter": "app.services.chat.chat_rate_limiter",
    "app.services.conversation_context": "app.services.chat.conversation_context",
    "app.services.message_intent": "app.services.chat.message_intent",
    "app.services.query_rewrite_service": "app.services.chat.query_rewrite_service",
    "app.services.chunk_store_service": "app.services.documents.chunk_store_service",
    "app.services.document_catalog_service": "app.services.documents.document_catalog_service",
    "app.services.document_chunk_metadata_service": "app.services.documents.document_chunk_metadata_service",
    "app.services.document_inventory": "app.services.documents.document_inventory",
    "app.services.document_preview_service": "app.services.documents.document_preview_service",
    "app.services.document_repository": "app.services.documents.document_repository",
    "app.services.document_service": "app.services.documents.document_service",
    "app.services.document_types": "app.services.documents.document_types",
    "app.services.history_memory_store": "app.services.history.history_memory_store",
    "app.services.history_serialization": "app.services.history.history_serialization",
    "app.services.history_service": "app.services.history.history_service",
    "app.services.history_turn_persistence": "app.services.history.history_turn_persistence",
    "app.services.document_parser": "app.services.ingestion.document_parser",
    "app.services.ingestion_chunk_builder": "app.services.ingestion.ingestion_chunk_builder",
    "app.services.ingestion_dispatcher": "app.services.ingestion.ingestion_dispatcher",
    "app.services.ingestion_service": "app.services.ingestion.ingestion_service",
    "app.services.opendataloader_parser": "app.services.ingestion.opendataloader_parser",
    "app.services.text_splitter": "app.services.ingestion.text_splitter",
    "app.services.keyword_service": "app.services.knowledge.keyword_service",
    "app.services.kg_manager": "app.services.knowledge.kg_manager",
    "app.services.topic_index_service": "app.services.knowledge.topic_index_service",
    "app.services.embedding_index_service": "app.services.providers.embedding_index_service",
    "app.services.nvidia_client": "app.services.providers.nvidia_client",
    "app.services.reranker_service": "app.services.providers.reranker_service",
    "app.services.web_search_service": "app.services.providers.web_search_service",
    "app.services.extractive_fallback_service": "app.services.rag.extractive_fallback_service",
    "app.services.rag_answer_strategies": "app.services.rag.rag_answer_strategies",
    "app.services.rag_answer_text": "app.services.rag.rag_answer_text",
    "app.services.rag_citations": "app.services.rag.rag_citations",
    "app.services.rag_comparison": "app.services.rag.rag_comparison",
    "app.services.rag_grounding": "app.services.rag.rag_grounding",
    "app.services.rag_prompting": "app.services.rag.rag_prompting",
    "app.services.rag_retrieval_policy": "app.services.rag.rag_retrieval_policy",
    "app.services.rag_retrieval": "app.services.rag.rag_retrieval",
    "app.services.rag_service": "app.services.rag.rag_service",
    "app.services.rag_types": "app.services.rag.rag_types",
}


class _LegacyServicesLoader(Loader):
    def __init__(self, canonical_name: str) -> None:
        self._canonical_name = canonical_name

    def exec_module(self, module: ModuleType) -> None:
        canonical_module = importlib.import_module(self._canonical_name)
        public_names = getattr(canonical_module, "__all__", None)
        if public_names is None:
            public_names = tuple(
                name for name in vars(canonical_module) if not name.startswith("_")
            )

        module.__dict__.update(
            {
                "__doc__": (
                    f"Compatibility module for {self._canonical_name!r}; "
                    "import the canonical domain package in new code."
                ),
                "__all__": tuple(public_names),
                "__getattr__": lambda name: getattr(canonical_module, name),
                "__dir__": lambda: sorted(set(module.__dict__) | set(dir(canonical_module))),
            }
        )


class _LegacyServicesFinder(MetaPathFinder):
    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        canonical_name = _LEGACY_MODULE_MAP.get(fullname)
        if canonical_name is None:
            return None
        return ModuleSpec(
            fullname,
            _LegacyServicesLoader(canonical_name),
            origin=f"compatibility alias for {canonical_name}",
        )


_legacy_finder = _LegacyServicesFinder()
sys.meta_path.insert(0, _legacy_finder)


def __getattr__(name: str) -> Any:
    if name in {"ServiceContainer", "build_container"}:
        return getattr(importlib.import_module("app.services.container"), name)

    legacy_fullname = f"app.services.{name}"
    if legacy_fullname in _LEGACY_MODULE_MAP:
        return importlib.import_module(legacy_fullname)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ServiceContainer",
    "build_container",
]
