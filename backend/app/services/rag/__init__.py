"""Retrieval-augmented generation (RAG) pipeline, citations, grounding, and answering."""

from app.services.rag.extractive_fallback_service import ExtractiveFallbackResult, ExtractiveFallbackService
from app.services.rag.rag_answer_strategies import (
    direct_comparison_shortcut,
    direct_context_shortcut,
    fallback_finalized_answer,
    interactive_generation_options,
    reasoning_context_summary,
)
from app.services.rag.rag_answer_text import (
    clean_model_thinking_summary,
    derive_citations_from_answer,
    extract_direct_qa_pair,
    normalize_answer_text,
    strip_citation_markers,
    strip_thinking_blocks,
    tokenize,
)
from app.services.rag.rag_citations import (
    citation_from_context,
    extract_citations,
    pdf_context_from_chunk,
    retrieved_chunk_from_candidate,
)
from app.services.rag.rag_comparison import comparison_subqueries
from app.services.rag.rag_grounding import (
    CONTEXT_FALLBACK_CHAR_LIMIT,
    clean_context_snippet,
    compose_fallback_answer,
    grounding_system_prompt,
    no_context_message,
    normalize_context_text,
    trim_text,
    ungrounded_answer_message,
)
from app.services.rag.rag_prompting import build_prompt, focus_context_text, select_contexts
from app.services.rag.rag_retrieval import RagRetrievalEngine
from app.services.rag.rag_retrieval_policy import (
    build_fts_query,
    rerank_pool_limit,
    rrf_score,
    select_final_chunks,
    select_rerank_candidate_pool,
    should_query_flat_collection,
)
from app.services.rag.rag_service import RagService
from app.services.rag.rag_types import (
    CandidateChunk,
    FinalizedAnswer,
    PreparedAnswer,
    RetrievalResult,
    RetrievedChunk,
    RetrievedContext,
)

__all__ = [
    "CONTEXT_FALLBACK_CHAR_LIMIT",
    "CandidateChunk",
    "ExtractiveFallbackResult",
    "ExtractiveFallbackService",
    "FinalizedAnswer",
    "PreparedAnswer",
    "RagRetrievalEngine",
    "RagService",
    "RetrievalResult",
    "RetrievedChunk",
    "RetrievedContext",
    "build_prompt",
    "citation_from_context",
    "build_fts_query",
    "clean_context_snippet",
    "clean_model_thinking_summary",
    "extract_citations",
    "comparison_subqueries",
    "extract_direct_qa_pair",
    "rerank_pool_limit",
    "rrf_score",
    "select_final_chunks",
    "select_rerank_candidate_pool",
    "should_query_flat_collection",
    "direct_comparison_shortcut",
    "direct_context_shortcut",
    "fallback_finalized_answer",
    "interactive_generation_options",
    "normalize_context_text",
    "reasoning_context_summary",
    "select_contexts",
    "derive_citations_from_answer",
    "normalize_answer_text",
    "strip_citation_markers",
    "strip_thinking_blocks",
    "tokenize",
    "trim_text",
    "grounding_system_prompt",
    "no_context_message",
    "ungrounded_answer_message",
    "compose_fallback_answer",
]
