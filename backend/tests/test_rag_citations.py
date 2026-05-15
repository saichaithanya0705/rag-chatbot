from __future__ import annotations

import unittest

from app.services.rag_citations import (
    citation_from_context,
    docling_source_metadata_from_metadata,
    pdf_context_from_chunk,
    retrieved_chunk_from_candidate,
)
from app.services.rag_types import CandidateChunk, RetrievedContext


class RagCitationMappingTests(unittest.TestCase):
    def test_candidate_metadata_chain_preserves_pdf_citation_contract(self) -> None:
        source_metadata = docling_source_metadata_from_metadata(
            {
                "parser": " docling ",
                "content_labels": '["section_header", "table", "paragraph", ""]',
                "source_text": "| Algorithm | Behavior |\n| Round Robin | Cycles through ready queue |",
                "source_refs": '["#/texts/0", "#/tables/0"]',
                "source_blocks": '[{"label": "table", "bbox": {"t": 90.0}}, "ignored"]',
                "has_table": "false",
            }
        )
        candidate = CandidateChunk(
            chunk_id="doc-1:1:0",
            collection_id="all_chunks",
            document_id="doc-1",
            pdf_name="Operating System Notes.pdf",
            page_number=1,
            chunk_index=0,
            text="Synthetic semantic chunk about a scheduling table.",
            fused_score=0.75,
            rerank_score=0.92,
            **source_metadata,
        )

        chunk = retrieved_chunk_from_candidate(candidate)
        context = pdf_context_from_chunk(chunk)
        citation = citation_from_context(context).model_dump(by_alias=True)

        self.assertFalse(hasattr(chunk, "rerank_score"))
        self.assertEqual(citation["parser"], "docling")
        self.assertEqual(citation["sourceLabels"], ["section_header", "table", "paragraph"])
        self.assertEqual(citation["sourceRefs"], ["#/texts/0", "#/tables/0"])
        self.assertEqual(citation["sourceLocation"], "section header + table")
        self.assertTrue(citation["hasTable"])
        self.assertEqual(citation["sourceBlocks"][0]["bbox"]["t"], 90.0)
        self.assertIn("Round Robin", citation["excerpt"])

    def test_web_context_maps_to_web_citation_without_pdf_fields(self) -> None:
        context = RetrievedContext(
            id="web:0:https://example.test/scheduling",
            kind="web",
            label="[Web: https://example.test/scheduling]",
            text="Scheduling reference.",
            excerpt="Scheduling reference.",
            title="Scheduling",
            url="https://example.test/scheduling",
        )

        citation = citation_from_context(context).model_dump(by_alias=True)

        self.assertEqual(citation["kind"], "web")
        self.assertEqual(citation["title"], "Scheduling")
        self.assertEqual(citation["url"], "https://example.test/scheduling")
        self.assertIsNone(citation["pdfName"])
        self.assertIsNone(citation["page"])
        self.assertIsNone(citation["chunkIndex"])


if __name__ == "__main__":
    unittest.main()
