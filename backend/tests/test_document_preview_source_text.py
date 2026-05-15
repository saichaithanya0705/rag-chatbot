from __future__ import annotations

import unittest

from app.services.document_preview_service import DocumentPreviewService
from app.services.document_service import StoredChunk


class _PreviewSource:
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
        html, total_pages = DocumentPreviewService(_PreviewSource()).render_preview_html(
            "sample.pdf",
            1,
            0,
            user_id="user-1",
        )

        self.assertEqual(total_pages, 1)
        self.assertIn('<span class="pdf-highlight">Structured source block for preview.</span>', html)

    def test_preview_escapes_document_text_before_inserting_highlight_markup(self) -> None:
        class SourceWithHtml(_PreviewSource):
            def get_page_text(
                self,
                pdf_name: str | None,
                page_number: int,
                *,
                document_id: str | None = None,
                user_id: str,
            ) -> tuple[str, int]:
                return "Intro\n\n<script>alert(1)</script> & source text\n\nOutro", 1

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
                    text="<script>alert(1)</script> & source text",
                )

        html, _total_pages = DocumentPreviewService(SourceWithHtml()).render_preview_html(
            "sample.pdf",
            1,
            0,
            user_id="user-1",
        )

        self.assertNotIn("<script>", html)
        self.assertIn(
            '<span class="pdf-highlight">&lt;script&gt;alert(1)&lt;/script&gt; &amp; source text</span>',
            html,
        )


if __name__ == "__main__":
    unittest.main()
