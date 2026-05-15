from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.schemas import CitationPayload, ToolCallPayload


@dataclass
class RetrievedChunk:
    chunk_id: str
    collection_id: str
    document_id: str
    pdf_name: str
    page_number: int
    chunk_index: int
    text: str
    parser: str | None = None
    content_labels: tuple[str, ...] = ()
    source_text: str | None = None
    source_refs: tuple[str, ...] = ()
    source_blocks: tuple[dict[str, Any], ...] = ()
    has_table: bool = False


@dataclass
class CandidateChunk:
    chunk_id: str
    collection_id: str
    document_id: str
    pdf_name: str
    page_number: int
    chunk_index: int
    text: str
    parser: str | None = None
    content_labels: tuple[str, ...] = ()
    source_text: str | None = None
    source_refs: tuple[str, ...] = ()
    source_blocks: tuple[dict[str, Any], ...] = ()
    has_table: bool = False
    fused_score: float = 0.0
    rerank_score: float | None = None


@dataclass(frozen=True)
class RetrievedContext:
    id: str
    kind: str
    label: str
    text: str
    excerpt: str
    document_id: str | None = None
    pdf_name: str | None = None
    page_number: int | None = None
    chunk_index: int | None = None
    parser: str | None = None
    source_text: str | None = None
    source_labels: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    source_blocks: tuple[dict[str, Any], ...] = ()
    source_location: str | None = None
    has_table: bool = False
    url: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]
    top_rerank_score: float | None


@dataclass
class PreparedAnswer:
    question: str
    prompt: str
    system_prompt: str
    contexts: list[RetrievedContext]
    shortcut_answer: str | None = None
    shortcut_citations: list[CitationPayload] = field(default_factory=list)
    tool_call: ToolCallPayload | None = None
    web_search_used: bool = False
    offline_warning: str | None = None
    cross_session_turn_count: int = 0
    response_mode: str = "grounded"
    trace_detail: str | None = None
    reasoning_segments: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FinalizedAnswer:
    answer: str
    citations: list[CitationPayload]
    model_thinking: str | None = None
    generation_warning: str | None = None
