from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.chroma_store import ChromaStore
from app.core.database import Database
from app.services.chunk_store_service import ChunkStoreService
from app.services.document_catalog_service import DocumentCatalogService
from app.services.document_chunk_metadata_service import DocumentChunkMetadataService
from app.services.document_repository import DocumentRepository
from app.services.document_types import RetrievalChunkCatalogEntry, StoredChunk


ACTIVE_DOCUMENT_STATUSES = {"queued", "parsing", "ocr", "chunking", "embedding", "clustering", "finalizing"}


class DocumentService:
    def __init__(
        self,
        *,
        database: Database,
        chroma_store: ChromaStore,
        collection_name: str = "all_chunks",
    ) -> None:
        self._catalog_service = DocumentCatalogService(
            database=database,
            collection_name=collection_name,
        )
        self._document_repository = DocumentRepository(database=database)
        self._chunk_store_service = ChunkStoreService(
            chroma_store=chroma_store,
            collection_name=collection_name,
        )
        self._chunk_metadata_service = DocumentChunkMetadataService(
            database=database,
            collection_getter=self._chunk_store_service.collection,
            catalog_service=self._catalog_service,
        )

    def list_documents(self, *, user_id: str) -> list[dict[str, Any]]:
        return self._document_repository.list_documents(user_id=user_id)

    def list_active_documents(self) -> list[dict[str, Any]]:
        return self._document_repository.list_active_documents(statuses=ACTIVE_DOCUMENT_STATUSES)

    def has_published_chunks(self, document_id: str, *, user_id: str) -> bool:
        return self._document_repository.has_published_chunks(document_id, user_id=user_id)

    def get_document_by_id(self, document_id: str, *, user_id: str) -> dict[str, Any] | None:
        return self._document_repository.get_document_by_id(document_id, user_id=user_id)

    def get_document_by_name(self, pdf_name: str, *, user_id: str) -> dict[str, Any] | None:
        return self._document_repository.get_document_by_name(pdf_name, user_id=user_id)

    def create_pending_document(
        self,
        *,
        document_id: str,
        pdf_name: str,
        source_path: Path,
        user_id: str,
    ) -> dict[str, Any]:
        existing = self.get_document_by_name(pdf_name, user_id=user_id)
        if existing:
            existing_status = str(existing["status"])
            if existing_status in ACTIVE_DOCUMENT_STATUSES:
                raise ValueError(f"{pdf_name} is already being indexed.")
            if existing_status == "error":
                self.remove_document_by_id(str(existing["id"]), user_id=user_id)
            else:
                raise ValueError(
                    f"{pdf_name} is already indexed. Delete it before uploading a replacement."
                )

        self._document_repository.create_pending_document(
            document_id=document_id,
            pdf_name=pdf_name,
            source_path=source_path,
            user_id=user_id,
        )
        return self.get_document_by_id(document_id, user_id=user_id) or {}

    def update_document_progress(
        self,
        document_id: str,
        *,
        user_id: str,
        status: str,
        progress: int,
        page_count: int | None = None,
        chunk_count: int | None = None,
        error_message: str | None = None,
        chunking_threshold: float | None = None,
    ) -> None:
        existing = self.get_document_by_id(document_id, user_id=user_id)
        if not existing:
            raise FileNotFoundError(f"Document '{document_id}' was not found.")

        self._document_repository.update_document_progress(
            document_id,
            user_id=user_id,
            status=status,
            progress=progress,
            page_count=page_count if page_count is not None else int(existing["page_count"]),
            chunk_count=chunk_count if chunk_count is not None else int(existing["chunk_count"]),
            error_message=error_message,
            chunking_threshold=(
                chunking_threshold if chunking_threshold is not None else existing["chunking_threshold"]
            ),
        )

    def mark_document_error(self, document_id: str, error_message: str, *, user_id: str) -> None:
        self.update_document_progress(
            document_id,
            user_id=user_id,
            status="error",
            progress=100,
            error_message=error_message,
        )

    def count_indexed_chunks(self, *, user_id: str) -> int:
        return self._document_repository.count_indexed_chunks(user_id=user_id)

    def sync_chunk_publication_flags(self) -> None:
        self._chunk_metadata_service.sync_chunk_publication_flags()

    def publish_document_chunks(self, document_id: str, *, user_id: str) -> None:
        self._chunk_store_service.publish_chunks(document_id, user_id)
        self._document_repository.mark_chunks_indexed(document_id, user_id=user_id)
        self._catalog_service.bump_retrieval_corpus_version()

    def retrieval_corpus_version(self) -> int:
        return self._catalog_service.retrieval_corpus_version()

    def clear_document_content(self, document_id: str, *, user_id: str) -> None:
        self._document_repository.clear_document_content(document_id, user_id=user_id)
        self._chunk_store_service.delete_chunks_for_document(document_id, user_id)
        self._catalog_service.bump_retrieval_corpus_version()

    def upsert_chunk_catalog_entries(
        self,
        entries: list[RetrievalChunkCatalogEntry],
    ) -> None:
        self._catalog_service.upsert_chunk_catalog_entries(entries)

    def update_chunk_collections(
        self,
        *,
        chunk_collection_ids: dict[str, str],
    ) -> None:
        self._catalog_service.update_chunk_collections(
            chunk_collection_ids=chunk_collection_ids,
        )

    def search_chunk_catalog(
        self,
        *,
        query: str,
        collection_id: str,
        user_id: str,
        limit: int,
    ) -> list[RetrievalChunkCatalogEntry]:
        return self._catalog_service.search_chunk_catalog(
            query=query,
            collection_id=collection_id,
            user_id=user_id,
            limit=limit,
        )

    def remove_document(self, pdf_name: str, *, user_id: str) -> None:
        stored = self.get_document_by_name(pdf_name, user_id=user_id)
        if not stored:
            return
        self.remove_document_by_id(str(stored["id"]), user_id=user_id)

    def remove_document_by_id(self, document_id: str, *, user_id: str) -> None:
        stored = self.get_document_by_id(document_id, user_id=user_id)
        if not stored:
            return

        status = str(stored["status"])
        if status in ACTIVE_DOCUMENT_STATUSES:
            raise ValueError(f"{stored['pdf_name']} is still indexing. Wait for it to finish before deleting it.")

        self.discard_document_by_id(document_id, user_id=user_id)

    def discard_document_by_id(self, document_id: str, *, user_id: str) -> None:
        stored = self.get_document_by_id(document_id, user_id=user_id)
        if not stored:
            return

        self.clear_document_content(str(stored["id"]), user_id=user_id)
        source_path = Path(str(stored["source_path"])).resolve()
        # Only delete the source file if it is stored in the application's uploads directory
        # to prevent deleting original local documents indexed directly via CLI/script.
        if "uploads" in str(source_path).lower() or source_path.name.startswith("tmp_"):
            source_path.unlink(missing_ok=True)
        self._document_repository.delete_document_record(str(stored["id"]), user_id=user_id)

    def store_document(
        self,
        *,
        document_id: str,
        user_id: str,
        pdf_name: str,
        source_path: Path,
        page_texts: list[str],
        chunk_count: int,
        chunking_threshold: float | None = None,
    ) -> None:
        self._document_repository.store_document(
            document_id=document_id,
            user_id=user_id,
            pdf_name=pdf_name,
            source_path=source_path,
            page_texts=page_texts,
            chunk_count=chunk_count,
            chunking_threshold=chunking_threshold,
        )

    def mark_document_indexed(self, document_id: str, *, user_id: str) -> None:
        self._document_repository.mark_document_indexed(document_id, user_id=user_id)

    def mark_user_documents_indexed(self, *, user_id: str) -> None:
        self._document_repository.mark_user_documents_indexed(user_id=user_id)

    def get_page_text(
        self,
        pdf_name: str | None,
        page_number: int,
        *,
        document_id: str | None = None,
        user_id: str,
    ) -> tuple[str, int]:
        stored = (
            self.get_document_by_id(document_id, user_id=user_id)
            if document_id
            else self.get_document_by_name(str(pdf_name), user_id=user_id)
        )
        if not stored:
            document_label = document_id or pdf_name or "document"
            raise FileNotFoundError(f"No ingested document matching '{document_label}' was found.")

        page_content = self._document_repository.get_page_text(
            document_id=str(stored["id"]),
            user_id=user_id,
            page_number=page_number,
        )
        if page_content is None:
            document_label = document_id or pdf_name or "document"
            raise FileNotFoundError(f"Page {page_number} was not found for '{document_label}'.")

        return page_content, int(stored["page_count"])

    def get_chunk(
        self,
        pdf_name: str | None,
        page_number: int,
        chunk_index: int,
        *,
        document_id: str | None = None,
        user_id: str,
    ) -> StoredChunk | None:
        return self._chunk_store_service.get_chunk(
            pdf_name=pdf_name,
            page_number=page_number,
            chunk_index=chunk_index,
            document_id=document_id,
            user_id=user_id,
        )

    def sync_active_chunk_metadata(self) -> None:
        active_documents = [
            {
                "document_id": str(document["id"]),
                "user_id": str(document["user_id"]),
            }
            for document in self.list_active_documents()
        ]
        if not active_documents:
            return

        for document in active_documents:
            self._chunk_metadata_service.sync_document_chunk_metadata(
                document_id=document["document_id"],
                user_id=document["user_id"],
            )
