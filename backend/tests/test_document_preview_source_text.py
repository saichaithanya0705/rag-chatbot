from __future__ import annotations

import unittest

from app.services.document_service import DocumentService, StoredChunk


class _PreviewDocumentService(DocumentService):
    def __init__(self) -> None:
        pass

    def get_page_text(
        self,
        pdf_name: str | None,
        page_number: int,
        *,
        document_id: str | None = None,
        user_id: str,
    ) -> tuple[str, int]:
        return "Intro\n\nStructured source block for preview.\n\nOutro", 1

    def get_chunk(
        self,
        pdf_name: str | None,
        page_number: int,
        chunk_index: int,
        *,
        document_id: str | None = None,
        user_id: str,
    ) -> StoredChunk | None:
        return StoredChunk(
            id="chunk-1",
            document_id="doc-1",
            user_id=user_id,
            pdf_name="sample.pdf",
            page_number=page_number,
            chunk_index=chunk_index,
            text="semantic chunk text not present verbatim",
            source_text="Structured source block for preview.",
        )


class DocumentPreviewSourceTextTests(unittest.TestCase):
    def test_preview_highlights_source_text_when_chunk_text_is_not_verbatim(self) -> None:
        html, total_pages = _PreviewDocumentService().render_preview_html(
            "sample.pdf",
            1,
            0,
            user_id="user-1",
        )

        self.assertEqual(total_pages, 1)
        self.assertIn('<span class="pdf-highlight">Structured source block for preview.</span>', html)


if __name__ == "__main__":
    unittest.main()
