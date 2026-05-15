from __future__ import annotations

import json
from typing import Any, Sequence

from app.models.schemas import CitationPayload
from app.services.rag_grounding import clean_context_snippet
from app.services.rag_types import CandidateChunk, RetrievedChunk, RetrievedContext


def retrieved_chunk_from_candidate(candidate: CandidateChunk) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=candidate.chunk_id,
        collection_id=candidate.collection_id,
        document_id=candidate.document_id,
        pdf_name=candidate.pdf_name,
        page_number=candidate.page_number,
        chunk_index=candidate.chunk_index,
        text=candidate.text,
        parser=candidate.parser,
        content_labels=candidate.content_labels,
        source_text=candidate.source_text,
        source_refs=candidate.source_refs,
        source_blocks=candidate.source_blocks,
        has_table=candidate.has_table,
    )


def pdf_context_from_chunk(chunk: RetrievedChunk) -> RetrievedContext:
    context_id = chunk.chunk_id
    excerpt_source = chunk.source_text or chunk.text
    return RetrievedContext(
        id=context_id,
        kind="pdf",
        label=f"[SourceID: {context_id}]",
        text=chunk.text,
        excerpt=clean_context_snippet(excerpt_source, max_chars=280),
        document_id=chunk.document_id,
        pdf_name=chunk.pdf_name,
        page_number=chunk.page_number,
        chunk_index=chunk.chunk_index,
        parser=chunk.parser,
        source_text=chunk.source_text,
        source_labels=chunk.content_labels,
        source_refs=chunk.source_refs,
        source_blocks=chunk.source_blocks,
        source_location=source_location_label(chunk.content_labels),
        has_table=chunk.has_table,
    )


def docling_source_metadata_from_metadata(metadata: dict[str, object]) -> dict[str, object]:
    labels = tuple(json_string_list(metadata.get("content_labels")))
    source_refs = tuple(json_string_list(metadata.get("source_refs")))
    source_blocks = tuple(json_dict_list(metadata.get("source_blocks")))
    parser = optional_metadata_text(metadata.get("parser"))
    source_text = optional_metadata_text(metadata.get("source_text"))
    has_table = metadata_bool(metadata.get("has_table")) or "table" in labels
    return {
        "parser": parser,
        "content_labels": labels,
        "source_text": source_text,
        "source_refs": source_refs,
        "source_blocks": source_blocks,
        "has_table": has_table,
    }


def optional_metadata_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def json_string_list(value: object) -> list[str]:
    raw_items = json_list(value)
    return [str(item) for item in raw_items if str(item).strip()]


def json_dict_list(value: object) -> list[dict[str, Any]]:
    raw_items = json_list(value)
    return [item for item in raw_items if isinstance(item, dict)]


def json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def metadata_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def source_location_label(labels: Sequence[str]) -> str | None:
    display_labels = [
        label.replace("_", " ")
        for label in labels
        if label and label not in {"text", "paragraph"}
    ]
    if not display_labels:
        return None
    return " + ".join(display_labels[:3])


def citation_from_context(context: RetrievedContext) -> CitationPayload:
    if context.kind == "web":
        return CitationPayload(
            id=context.id,
            kind="web",
            pdf_name=None,
            page=None,
            chunk_index=None,
            excerpt=context.excerpt,
            title=context.title,
            url=context.url,
        )

    return CitationPayload(
        id=context.id,
        kind="pdf",
        document_id=context.document_id,
        pdf_name=context.pdf_name,
        page=context.page_number,
        chunk_index=context.chunk_index,
        excerpt=context.excerpt,
        parser=context.parser,
        source_text=context.source_text,
        source_labels=list(context.source_labels),
        source_refs=list(context.source_refs),
        source_blocks=list(context.source_blocks),
        source_location=context.source_location,
        has_table=context.has_table,
        title=context.title,
        url=context.url,
    )
