from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StoredChunk:
    id: str
    document_id: str
    user_id: str
    pdf_name: str
    page_number: int
    chunk_index: int
    text: str
    char_start: int | None = None
    char_end: int | None = None
    source_text: str | None = None


@dataclass(frozen=True)
class RetrievalChunkCatalogEntry:
    chunk_id: str
    document_id: str
    user_id: str
    pdf_name: str
    page_number: int
    chunk_index: int
    text: str
    collection_id: str | None = None
    is_indexed: bool = False
