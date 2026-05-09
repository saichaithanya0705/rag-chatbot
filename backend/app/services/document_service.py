from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.chroma_store import ChromaStore
from app.core.database import Database


ACTIVE_DOCUMENT_STATUSES = {"queued", "parsing", "ocr", "chunking", "embedding", "clustering", "finalizing"}
WHITESPACE_PATTERN = re.compile(r"\s+")
PREVIEW_NOISE_LINE_PATTERN = re.compile(
    r"(?im)^\s*(?:page\s+\d+\b.*|©?\s*copyright\b.*|[^ \n\r]*copyright\b.*)$"
)
PREVIEW_NOISE_INLINE_PATTERN = re.compile(
    r"(?i)\s*(?:©\s*)?copyright[^\n\r]*|\s+page\s+\d+\b"
)


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
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, status
                FROM ingested_documents
                """
            ).fetchall()

        document_state_by_id = {
            str(row["id"]): {
                "user_id": str(row["user_id"]),
                "is_indexed": 1 if str(row["status"]) == "indexed" else 0,
            }
            for row in rows
        }
        chunk_rows = self._collection().get(include=["documents", "metadatas"])
        chunk_ids = [str(chunk_id) for chunk_id in chunk_rows.get("ids", [])]
        documents = [str(text) for text in chunk_rows.get("documents", [])]
        metadatas = [dict(metadata or {}) for metadata in chunk_rows.get("metadatas", [])]
        catalog_entries = [
            RetrievalChunkCatalogEntry(
                chunk_id=str(chunk_id),
                document_id=str(metadata.get("document_id", "")),
                user_id=self._normalized_chunk_user_id(
                    metadata,
                    document_state_by_id=document_state_by_id,
                ),
                pdf_name=str(metadata.get("pdf_name", "")),
                page_number=int(metadata.get("page_number", 0)),
                chunk_index=int(metadata.get("chunk_index", 0)),
                text=str(text),
                collection_id=(
                    str(metadata.get("collection_id")).strip()
                    if metadata.get("collection_id") is not None
                    else None
                ),
                is_indexed=self._normalized_chunk_is_indexed(
                    metadata,
                    document_state_by_id=document_state_by_id,
                ),
            )
            for chunk_id, text, metadata in zip(
                chunk_ids,
                documents,
                metadatas,
                strict=False,
            )
            if metadata
        ]

        updated_ids: list[str] = []
        updated_metadatas: list[dict[str, object]] = []
        for chunk_id, metadata in zip(chunk_ids, metadatas, strict=False):
            document_id = str(metadata.get("document_id", "")).strip()
            document_state = document_state_by_id.get(document_id)
            if not document_id or document_state is None:
                continue
            normalized_user_id = str(document_state["user_id"])
            expected_value = int(document_state["is_indexed"])
            current_value = int(metadata.get("is_indexed", -1))
            current_user_id = str(metadata.get("user_id", "")).strip()
            if current_value == expected_value and current_user_id == normalized_user_id:
                continue
            updated_ids.append(chunk_id)
            updated_metadatas.append(
                {
                    **metadata,
                    "user_id": normalized_user_id,
                    "is_indexed": expected_value,
                }
            )

        if updated_ids:
            self._collection().update(ids=updated_ids, metadatas=updated_metadatas)
            self._bump_retrieval_corpus_version()
        self._sync_chunk_catalog(catalog_entries)

    @staticmethod
    def _normalized_chunk_user_id(
        metadata: dict[str, object],
        *,
        document_state_by_id: dict[str, dict[str, object]],
    ) -> str:
        stored_user_id = str(metadata.get("user_id", "")).strip()
        if stored_user_id:
            return stored_user_id

        document_id = str(metadata.get("document_id", "")).strip()
        document_state = document_state_by_id.get(document_id)
        if document_state is None:
            return stored_user_id
        return str(document_state["user_id"])

    @staticmethod
    def _normalized_chunk_is_indexed(
        metadata: dict[str, object],
        *,
        document_state_by_id: dict[str, dict[str, object]],
    ) -> bool:
        document_id = str(metadata.get("document_id", "")).strip()
        document_state = document_state_by_id.get(document_id)
        if document_state is None:
            return bool(metadata.get("is_indexed", 0))
        return bool(document_state["is_indexed"])

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
        self._bump_retrieval_corpus_version()

    def retrieval_corpus_version(self) -> int:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT version FROM retrieval_corpus_state WHERE id = 1"
            ).fetchone()
        return int(row["version"]) if row else 0

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
        self._bump_retrieval_corpus_version()

    def upsert_chunk_catalog_entries(
        self,
        entries: list[RetrievalChunkCatalogEntry],
    ) -> None:
        if not entries:
            return

        with self._database.connect() as connection:
            connection.executemany(
                """
                INSERT INTO retrieval_chunks (
                    chunk_id,
                    document_id,
                    user_id,
                    pdf_name,
                    page_number,
                    chunk_index,
                    collection_id,
                    is_indexed,
                    text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    document_id = excluded.document_id,
                    user_id = excluded.user_id,
                    pdf_name = excluded.pdf_name,
                    page_number = excluded.page_number,
                    chunk_index = excluded.chunk_index,
                    collection_id = excluded.collection_id,
                    is_indexed = excluded.is_indexed,
                    text = excluded.text
                """,
                [
                    (
                        entry.chunk_id,
                        entry.document_id,
                        entry.user_id,
                        entry.pdf_name,
                        entry.page_number,
                        entry.chunk_index,
                        entry.collection_id,
                        int(entry.is_indexed),
                        entry.text,
                    )
                    for entry in entries
                ],
            )

    def update_chunk_collections(
        self,
        *,
        chunk_collection_ids: dict[str, str],
    ) -> None:
        if not chunk_collection_ids:
            return

        with self._database.connect() as connection:
            connection.executemany(
                """
                UPDATE retrieval_chunks
                SET collection_id = ?
                WHERE chunk_id = ?
                """,
                [
                    (collection_id, chunk_id)
                    for chunk_id, collection_id in chunk_collection_ids.items()
                ],
            )

    def search_chunk_catalog(
        self,
        *,
        query: str,
        collection_id: str,
        user_id: str,
        limit: int,
    ) -> list[RetrievalChunkCatalogEntry]:
        where_clause = "retrieval_chunks_fts MATCH ? AND rc.user_id = ? AND rc.is_indexed = 1"
        parameters: list[object] = [query, user_id]
        if collection_id not in {"all-pdfs", self._collection_name}:
            where_clause += " AND rc.collection_id = ?"
            parameters.append(collection_id)
        parameters.append(limit)

        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    rc.chunk_id,
                    rc.document_id,
                    rc.user_id,
                    rc.pdf_name,
                    rc.page_number,
                    rc.chunk_index,
                    rc.collection_id,
                    rc.is_indexed,
                    rc.text
                FROM retrieval_chunks_fts
                INNER JOIN retrieval_chunks AS rc
                    ON rc.rowid = retrieval_chunks_fts.rowid
                WHERE {where_clause}
                ORDER BY bm25(retrieval_chunks_fts), rc.page_number, rc.chunk_index
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        return [
            RetrievalChunkCatalogEntry(
                chunk_id=str(row["chunk_id"]),
                document_id=str(row["document_id"]),
                user_id=str(row["user_id"]),
                pdf_name=str(row["pdf_name"]),
                page_number=int(row["page_number"]),
                chunk_index=int(row["chunk_index"]),
                collection_id=(
                    str(row["collection_id"])
                    if row["collection_id"] is not None
                    else None
                ),
                is_indexed=bool(row["is_indexed"]),
                text=str(row["text"]),
            )
            for row in rows
        ]

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

    def render_preview_html(
        self,
        pdf_name: str | None,
        page_number: int,
        chunk_index: int,
        *,
        document_id: str | None = None,
        user_id: str,
    ) -> tuple[str, int]:
        page_text, total_pages = self.get_page_text(
            pdf_name,
            page_number,
            document_id=document_id,
            user_id=user_id,
        )
        chunk = self.get_chunk(
            pdf_name,
            page_number,
            chunk_index,
            document_id=document_id,
            user_id=user_id,
        )
        highlighted = page_text

        if chunk and chunk.text:
            match_span = (
                (chunk.char_start, chunk.char_end)
                if chunk.char_start is not None and chunk.char_end is not None
                else self._find_chunk_span(page_text, chunk.text)
            )
            if match_span is None and chunk.source_text:
                match_span = self._find_chunk_span(page_text, chunk.source_text)
            if match_span is not None:
                match_start, match_end = match_span
                highlighted = (
                    page_text[:match_start]
                    + f"[[[highlight]]]{page_text[match_start:match_end]}[[[/highlight]]]"
                    + page_text[match_end:]
                )

        highlighted = PREVIEW_NOISE_LINE_PATTERN.sub("", highlighted)
        highlighted = PREVIEW_NOISE_INLINE_PATTERN.sub("", highlighted)
        highlighted = re.sub(r"\n{3,}", "\n\n", highlighted).strip()
        escaped = html.escape(highlighted).replace("\n\n", "<br><br>").replace("\n", "<br>")
        escaped = escaped.replace(
            "[[[highlight]]]",
            '<span class="pdf-highlight">',
        ).replace("[[[/highlight]]]", "</span>")
        return escaped, total_pages

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

    def _bump_retrieval_corpus_version(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE retrieval_corpus_state
                SET version = version + 1
                WHERE id = 1
                """
            )

    def _sync_chunk_catalog(
        self,
        entries: list[RetrievalChunkCatalogEntry],
    ) -> None:
        desired_by_id = {entry.chunk_id: entry for entry in entries}
        with self._database.connect() as connection:
            existing_rows = connection.execute(
                """
                SELECT
                    chunk_id,
                    document_id,
                    user_id,
                    pdf_name,
                    page_number,
                    chunk_index,
                    collection_id,
                    is_indexed,
                    text
                FROM retrieval_chunks
                """
            ).fetchall()
            existing_by_id = {
                str(row["chunk_id"]): RetrievalChunkCatalogEntry(
                    chunk_id=str(row["chunk_id"]),
                    document_id=str(row["document_id"]),
                    user_id=str(row["user_id"]),
                    pdf_name=str(row["pdf_name"]),
                    page_number=int(row["page_number"]),
                    chunk_index=int(row["chunk_index"]),
                    collection_id=(
                        str(row["collection_id"])
                        if row["collection_id"] is not None
                        else None
                    ),
                    is_indexed=bool(row["is_indexed"]),
                    text=str(row["text"]),
                )
                for row in existing_rows
            }

            deleted_chunk_ids = [
                chunk_id
                for chunk_id in existing_by_id
                if chunk_id not in desired_by_id
            ]
            if deleted_chunk_ids:
                connection.executemany(
                    "DELETE FROM retrieval_chunks WHERE chunk_id = ?",
                    [(chunk_id,) for chunk_id in deleted_chunk_ids],
                )

        changed_entries = [
            entry
            for chunk_id, entry in desired_by_id.items()
            if existing_by_id.get(chunk_id) != entry
        ]
        self.upsert_chunk_catalog_entries(changed_entries)

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
            self._sync_document_chunk_metadata(
                document_id=document["document_id"],
                user_id=document["user_id"],
            )

    def _sync_document_chunk_metadata(self, *, document_id: str, user_id: str) -> None:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, user_id, is_indexed, collection_id
                FROM retrieval_chunks
                WHERE document_id = ? AND user_id = ?
                """,
                (document_id, user_id),
            ).fetchall()

        catalog_by_chunk_id = {
            str(row["chunk_id"]): {
                "user_id": str(row["user_id"]),
                "is_indexed": int(row["is_indexed"]),
                "collection_id": (
                    str(row["collection_id"])
                    if row["collection_id"] is not None
                    else None
                ),
            }
            for row in rows
        }
        if not catalog_by_chunk_id:
            return

        chunk_rows = self._collection().get(
            where={"$and": [{"document_id": document_id}, {"user_id": user_id}]},
            include=["metadatas"],
        )
        chunk_ids = [str(chunk_id) for chunk_id in chunk_rows.get("ids", [])]
        metadatas = [dict(metadata or {}) for metadata in chunk_rows.get("metadatas", [])]

        updated_ids: list[str] = []
        updated_metadatas: list[dict[str, object]] = []
        for chunk_id, metadata in zip(chunk_ids, metadatas, strict=False):
            expected = catalog_by_chunk_id.get(chunk_id)
            if expected is None:
                continue

            current_user_id = str(metadata.get("user_id", "")).strip()
            current_is_indexed = int(metadata.get("is_indexed", -1))
            current_collection_id = (
                str(metadata.get("collection_id")).strip()
                if metadata.get("collection_id") is not None
                else None
            )
            if (
                current_user_id == expected["user_id"]
                and current_is_indexed == expected["is_indexed"]
                and current_collection_id == expected["collection_id"]
            ):
                continue

            updated_ids.append(chunk_id)
            updated_metadatas.append(
                {
                    **metadata,
                    "user_id": expected["user_id"],
                    "is_indexed": expected["is_indexed"],
                    "collection_id": expected["collection_id"],
                }
            )

        if updated_ids:
            self._collection().update(ids=updated_ids, metadatas=updated_metadatas)
