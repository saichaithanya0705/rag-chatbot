from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.document_catalog_service import DocumentCatalogService
from app.services.document_chunk_metadata_service import DocumentChunkMetadataService
from app.core.chroma_store import ChromaStore
from app.core.database import Database
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
        self._database = database
        self._chroma_store = chroma_store
        self._collection_name = collection_name
        self._catalog_service = DocumentCatalogService(
            database=database,
            collection_name=collection_name,
        )
        self._chunk_metadata_service = DocumentChunkMetadataService(
            database=database,
            collection_getter=self._collection,
            catalog_service=self._catalog_service,
        )

    def _collection(self) -> Any:
        return self._chroma_store.collection(self._collection_name)

    def list_documents(self, *, user_id: str) -> list[dict[str, Any]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    user_id,
                    pdf_name,
                    source_path,
                    page_count,
                    chunk_count,
                    status,
                    progress,
                    error_message,
                    chunking_threshold,
                    created_at,
                    updated_at
                FROM ingested_documents
                WHERE user_id = ?
                ORDER BY updated_at DESC, created_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_active_documents(self) -> list[dict[str, Any]]:
        placeholders = ", ".join("?" for _ in ACTIVE_DOCUMENT_STATUSES)
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    id,
                    user_id,
                    pdf_name,
                    source_path,
                    page_count,
                    chunk_count,
                    status,
                    progress,
                    error_message,
                    chunking_threshold,
                    created_at,
                    updated_at
                FROM ingested_documents
                WHERE status IN ({placeholders})
                ORDER BY created_at ASC, updated_at ASC, id ASC
                """,
                tuple(sorted(ACTIVE_DOCUMENT_STATUSES)),
            ).fetchall()
        return [dict(row) for row in rows]

    def has_published_chunks(self, document_id: str, *, user_id: str) -> bool:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM retrieval_chunks
                WHERE document_id = ? AND user_id = ? AND is_indexed = 1
                LIMIT 1
                """,
                (document_id, user_id),
            ).fetchone()
        return row is not None

    def get_document_by_id(self, document_id: str, *, user_id: str) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    user_id,
                    pdf_name,
                    source_path,
                    page_count,
                    chunk_count,
                    status,
                    progress,
                    error_message,
                    chunking_threshold,
                    created_at,
                    updated_at
                FROM ingested_documents
                WHERE id = ? AND user_id = ?
                """,
                (document_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def get_document_by_name(self, pdf_name: str, *, user_id: str) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    user_id,
                    pdf_name,
                    source_path,
                    page_count,
                    chunk_count,
                    status,
                    progress,
                    error_message,
                    chunking_threshold,
                    created_at,
                    updated_at
                FROM ingested_documents
                WHERE pdf_name = ? AND user_id = ?
                """,
                (pdf_name, user_id),
            ).fetchone()
        return dict(row) if row else None

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

        timestamp = datetime.now(UTC).isoformat()
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO ingested_documents (
                    id,
                    user_id,
                    pdf_name,
                    source_path,
                    page_count,
                    chunk_count,
                    status,
                    progress,
                    error_message,
                    chunking_threshold,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    user_id,
                    pdf_name,
                    str(source_path),
                    0,
                    0,
                    "queued",
                    0,
                    None,
                    None,
                    timestamp,
                    timestamp,
                ),
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

        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE ingested_documents
                SET status = ?,
                    progress = ?,
                    page_count = ?,
                    chunk_count = ?,
                    error_message = ?,
                    chunking_threshold = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    status,
                    max(0, min(progress, 100)),
                    page_count if page_count is not None else int(existing["page_count"]),
                    chunk_count if chunk_count is not None else int(existing["chunk_count"]),
                    error_message,
                    chunking_threshold if chunking_threshold is not None else existing["chunking_threshold"],
                    datetime.now(UTC).isoformat(),
                    document_id,
                    user_id,
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
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(chunk_count), 0) AS total_chunks
                FROM ingested_documents
                WHERE user_id = ? AND status = 'indexed'
                """,
                (user_id,),
            ).fetchone()
        return int(row["total_chunks"]) if row and row["total_chunks"] is not None else 0

    def sync_chunk_publication_flags(self) -> None:
        self._chunk_metadata_service.sync_chunk_publication_flags()

    def publish_document_chunks(self, document_id: str, *, user_id: str) -> None:
        rows = self._collection().get(
            where={"$and": [{"document_id": document_id}, {"user_id": user_id}]},
            include=["metadatas"],
        )
        chunk_ids = [str(chunk_id) for chunk_id in rows.get("ids", [])]
        if not chunk_ids:
            return
        updated_metadatas = [
            {**dict(metadata or {}), "is_indexed": 1}
            for metadata in rows.get("metadatas", [])
        ]
        self._collection().update(ids=chunk_ids, metadatas=updated_metadatas)
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE retrieval_chunks
                SET is_indexed = 1
                WHERE document_id = ? AND user_id = ?
                """,
                (document_id, user_id),
            )
        self._catalog_service.bump_retrieval_corpus_version()

    def retrieval_corpus_version(self) -> int:
        return self._catalog_service.retrieval_corpus_version()

    def clear_document_content(self, document_id: str, *, user_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                DELETE FROM ingested_pages
                WHERE document_id IN (
                    SELECT id
                    FROM ingested_documents
                    WHERE id = ? AND user_id = ?
                )
                """,
                (document_id, user_id),
            )
            connection.execute(
                """
                DELETE FROM retrieval_chunks
                WHERE document_id = ? AND user_id = ?
                """,
                (document_id, user_id),
            )

        self._collection().delete(where={"$and": [{"document_id": document_id}, {"user_id": user_id}]})
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
        source_path = Path(str(stored["source_path"]))
        source_path.unlink(missing_ok=True)

        with self._database.connect() as connection:
            connection.execute(
                "DELETE FROM ingested_documents WHERE id = ? AND user_id = ?",
                (stored["id"], user_id),
            )

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
        timestamp = datetime.now(UTC).isoformat()
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE ingested_documents
                SET pdf_name = ?,
                    source_path = ?,
                    page_count = ?,
                    chunk_count = ?,
                    status = 'finalizing',
                    progress = 92,
                    error_message = NULL,
                    chunking_threshold = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    pdf_name,
                    str(source_path),
                    len(page_texts),
                    chunk_count,
                    chunking_threshold,
                    timestamp,
                    document_id,
                    user_id,
                ),
            )
            connection.execute(
                """
                DELETE FROM ingested_pages
                WHERE document_id IN (
                    SELECT id
                    FROM ingested_documents
                    WHERE id = ? AND user_id = ?
                )
                """,
                (document_id, user_id),
            )
            connection.executemany(
                """
                INSERT INTO ingested_pages (document_id, page_number, content)
                VALUES (?, ?, ?)
                """,
                [(document_id, index + 1, content) for index, content in enumerate(page_texts)],
            )

    def mark_document_indexed(self, document_id: str, *, user_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE ingested_documents
                SET status = 'indexed',
                    progress = 100,
                    error_message = NULL,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (datetime.now(UTC).isoformat(), document_id, user_id),
            )

    def mark_user_documents_indexed(self, *, user_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE ingested_documents
                SET status = 'indexed',
                    progress = 100,
                    error_message = NULL,
                    updated_at = ?
                WHERE user_id = ? AND status = 'finalizing'
                """,
                (datetime.now(UTC).isoformat(), user_id),
            )

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

        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT pages.content
                FROM ingested_pages AS pages
                INNER JOIN ingested_documents AS documents
                    ON documents.id = pages.document_id
                WHERE documents.id = ? AND documents.user_id = ? AND pages.page_number = ?
                """,
                (stored["id"], user_id, page_number),
            ).fetchone()

        if not row:
            document_label = document_id or pdf_name or "document"
            raise FileNotFoundError(f"Page {page_number} was not found for '{document_label}'.")

        return str(row["content"]), int(stored["page_count"])

    def get_chunk(
        self,
        pdf_name: str | None,
        page_number: int,
        chunk_index: int,
        *,
        document_id: str | None = None,
        user_id: str,
    ) -> StoredChunk | None:
        where_clauses: list[dict[str, object]] = [
            {"user_id": user_id},
            {"page_number": page_number},
            {"chunk_index": chunk_index},
        ]
        if document_id:
            where_clauses.append({"document_id": document_id})
        elif pdf_name is not None:
            where_clauses.append({"pdf_name": pdf_name})
        result = self._collection().get(
            where={"$and": where_clauses},
            include=["documents", "metadatas"],
        )

        ids = result.get("ids", [])
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        if not ids:
            return None

        metadata = metadatas[0]
        return StoredChunk(
            id=ids[0],
            document_id=str(metadata["document_id"]),
            user_id=str(metadata["user_id"]),
            pdf_name=str(metadata["pdf_name"]),
            page_number=int(metadata["page_number"]),
            chunk_index=int(metadata["chunk_index"]),
            text=str(documents[0]),
            char_start=int(metadata["char_start"]) if metadata.get("char_start") is not None else None,
            char_end=int(metadata["char_end"]) if metadata.get("char_end") is not None else None,
            source_text=(
                str(metadata.get("source_text"))
                if metadata.get("source_text") is not None and str(metadata.get("source_text")).strip()
                else None
            ),
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
