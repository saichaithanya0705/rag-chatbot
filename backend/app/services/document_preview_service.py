from __future__ import annotations

import html
import re
from typing import Protocol

from app.services.document_service import StoredChunk


PREVIEW_NOISE_LINE_PATTERN = re.compile(
    r"(?im)^\s*(?:page\s+\d+\b.*|©?\s*copyright\b.*|[^ \n\r]*copyright\b.*)$"
)
PREVIEW_NOISE_INLINE_PATTERN = re.compile(
    r"(?i)\s*(?:©\s*)?copyright[^\n\r]*|\s+page\s+\d+\b"
)


class DocumentPreviewSource(Protocol):
    def get_page_text(
        self,
        pdf_name: str | None,
        page_number: int,
        *,
        document_id: str | None = None,
        user_id: str,
    ) -> tuple[str, int]: ...

    def get_chunk(
        self,
        pdf_name: str | None,
        page_number: int,
        chunk_index: int,
        *,
        document_id: str | None = None,
        user_id: str,
    ) -> StoredChunk | None: ...


class DocumentPreviewService:
    def __init__(self, source: DocumentPreviewSource) -> None:
        self._source = source

    def render_preview_html(
        self,
        pdf_name: str | None,
        page_number: int,
        chunk_index: int,
        *,
        document_id: str | None = None,
        user_id: str,
    ) -> tuple[str, int]:
        page_text, total_pages = self._source.get_page_text(
            pdf_name,
            page_number,
            document_id=document_id,
            user_id=user_id,
        )
        chunk = self._source.get_chunk(
            pdf_name,
            page_number,
            chunk_index,
            document_id=document_id,
            user_id=user_id,
        )
        highlighted = self._highlight_chunk_text(page_text, chunk)
        return self._render_html(highlighted), total_pages

    def _highlight_chunk_text(self, page_text: str, chunk: StoredChunk | None) -> str:
        if chunk is None or not chunk.text:
            return page_text

        match_span = (
            (chunk.char_start, chunk.char_end)
            if chunk.char_start is not None and chunk.char_end is not None
            else self._find_chunk_span(page_text, chunk.text)
        )
        if match_span is None and chunk.source_text:
            match_span = self._find_chunk_span(page_text, chunk.source_text)
        if match_span is None:
            return page_text

        match_start, match_end = match_span
        return (
            page_text[:match_start]
            + f"[[[highlight]]]{page_text[match_start:match_end]}[[[/highlight]]]"
            + page_text[match_end:]
        )

    @staticmethod
    def _render_html(text: str) -> str:
        cleaned = PREVIEW_NOISE_LINE_PATTERN.sub("", text)
        cleaned = PREVIEW_NOISE_INLINE_PATTERN.sub("", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        escaped = html.escape(cleaned).replace("\n\n", "<br><br>").replace("\n", "<br>")
        return escaped.replace(
            "[[[highlight]]]",
            '<span class="pdf-highlight">',
        ).replace("[[[/highlight]]]", "</span>")

    @staticmethod
    def _find_chunk_span(page_text: str, chunk_text: str) -> tuple[int, int] | None:
        exact_match_start = page_text.find(chunk_text)
        if exact_match_start >= 0:
            return exact_match_start, exact_match_start + len(chunk_text)

        normalized_chunk = " ".join(chunk_text.split())
        if not normalized_chunk:
            return None

        whitespace_flexible_pattern = r"\s+".join(
            re.escape(part)
            for part in normalized_chunk.split()
        )
        match = re.search(whitespace_flexible_pattern, page_text)
        if match is None:
            return None

        return match.span()
