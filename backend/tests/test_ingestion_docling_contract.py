from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.services.document_parser import ParsedBlock, ParsedDocument, ParsedPage
from app.services.ingestion_service import IngestionService


class _FakeDocumentParser:
    parser_name = "docling"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        return ParsedDocument(
            parser_name=self.parser_name,
            pages=[
                ParsedPage(
                    page_number=1,
                    blocks=[
                        ParsedBlock(
                            text="System overview",
                            page_number=1,
                            label="section_header",
                            top=10.0,
                            bottom=30.0,
                            page_height=800.0,
                            bbox={"l": 10.0, "t": 10.0, "r": 400.0, "b": 30.0},
                            source_ref="#/texts/0",
                        ),
                        ParsedBlock(
                            text="| Component | Role |\n| --- | --- |\n| Parser | Structured extraction |",
                            page_number=1,
                            label="table",
                            top=40.0,
                            bottom=120.0,
                            page_height=800.0,
                            bbox={"l": 10.0, "t": 40.0, "r": 500.0, "b": 120.0},
                            source_ref="#/tables/0",
                        ),
                    ],
                )
            ],
        )


class _FakeDocumentService:
    def __init__(self) -> None:
        self.stored_pages: list[str] = []

    def create_pending_document(self, **kwargs: object) -> None:
        return None

    def get_document_by_id(self, document_id: str, *, user_id: str) -> dict[str, object] | None:
        return {"pdf_name": "docling.pdf"}

    def update_document_progress(self, *args: object, **kwargs: object) -> None:
        return None

    def clear_document_content(self, document_id: str, *, user_id: str) -> None:
        return None

    def mark_document_error(self, document_id: str, error_message: str, *, user_id: str) -> None:
        raise AssertionError(error_message)

    def upsert_chunk_catalog_entries(self, entries: list[object]) -> None:
        return None

    def store_document(self, *, page_texts: list[str], **kwargs: object) -> None:
        self.stored_pages = page_texts

    def publish_document_chunks(self, document_id: str, *, user_id: str) -> None:
        return None


class _FakeKeywordService:
    pass


class _FakeNvidiaClient:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _text in texts]


class _FakeSplitter:
    async def split_text(self, text: str, *, threshold: float | None = None, blocks: list[str] | None = None) -> list[str]:
        return ["Synthetic chunk about the parser table"]


class _FakeCollection:
    def __init__(self) -> None:
        self.upserts: list[dict[str, object]] = []

    def upsert(self, **kwargs: object) -> None:
        self.upserts.append(kwargs)


class _FakeChromaStore:
    max_batch_size = 96

    def __init__(self) -> None:
        self.collection_instance = _FakeCollection()

    def collection(self, name: str = "all_chunks") -> _FakeCollection:
        return self.collection_instance


class _FakeTopicIndexService:
    pass


class IngestionDoclingContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_pdf_uses_docling_pages_and_adds_source_metadata(self) -> None:
        document_service = _FakeDocumentService()
        chroma_store = _FakeChromaStore()
        ingestion = IngestionService(
            document_service=document_service,  # type: ignore[arg-type]
            keyword_service=_FakeKeywordService(),  # type: ignore[arg-type]
            nvidia_client=_FakeNvidiaClient(),  # type: ignore[arg-type]
            text_splitter=_FakeSplitter(),  # type: ignore[arg-type]
            chroma_store=chroma_store,  # type: ignore[arg-type]
            topic_index_service=_FakeTopicIndexService(),  # type: ignore[arg-type]
            document_parser=_FakeDocumentParser(),  # type: ignore[arg-type]
        )

        with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf:
            result = await ingestion.ingest_pdf(
                Path(pdf.name),
                document_id="doc-1",
                pdf_name="docling.pdf",
                user_id="user-1",
            )

        self.assertEqual(result.page_count, 1)
        self.assertEqual(result.chunk_count, 1)
        self.assertEqual(
            document_service.stored_pages,
            [
                "System overview\n\n"
                "| Component | Role |\n| --- | --- |\n| Parser | Structured extraction |"
            ],
        )
        metadata = chroma_store.collection_instance.upserts[0]["metadatas"][0]  # type: ignore[index]
        self.assertEqual(metadata["parser"], "docling")
        self.assertEqual(metadata["content_labels"], '["section_header", "table"]')
        self.assertEqual(metadata["page_start"], 1)
        self.assertEqual(metadata["page_end"], 1)
        self.assertEqual(metadata["has_table"], 1)
        self.assertIn("Structured extraction", metadata["source_text"])
        self.assertIn("#/tables/0", metadata["source_refs"])
        self.assertIn('"label": "table"', metadata["source_blocks"])


if __name__ == "__main__":
    unittest.main()
