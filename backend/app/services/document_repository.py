from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.database import Database


class DocumentRepository:
    def __init__(self, *, database: Database) -> None:
        self._database = database

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

    def list_active_documents(self, *, statuses: set[str]) -> list[dict[str, Any]]:
        placeholders = ", ".join("?" for _ in statuses)
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
                tuple(sorted(statuses)),
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
    ) -> None:
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

    def update_document_progress(
        self,
        document_id: str,
        *,
        user_id: str,
        status: str,
        progress: int,
        page_count: int,
        chunk_count: int,
        error_message: str | None,
        chunking_threshold: float | None,
    ) -> None:
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
                    page_count,
                    chunk_count,
                    error_message,
                    chunking_threshold,
                    datetime.now(UTC).isoformat(),
                    document_id,
                    user_id,
                ),
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

    def count_indexed_chunks_all(self) -> int:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(chunk_count), 0) AS total_chunks
                FROM ingested_documents
                WHERE status = 'indexed'
                """
            ).fetchone()
        return int(row["total_chunks"]) if row and row["total_chunks"] is not None else 0

    def mark_chunks_indexed(self, document_id: str, *, user_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE retrieval_chunks
                SET is_indexed = 1
                WHERE document_id = ? AND user_id = ?
                """,
                (document_id, user_id),
            )

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

    def delete_document_record(self, document_id: str, *, user_id: str) -> None:
        with self._database.connect() as connection:
            connection.execute(
                "DELETE FROM ingested_documents WHERE id = ? AND user_id = ?",
                (document_id, user_id),
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

    def get_page_text(self, *, document_id: str, user_id: str, page_number: int) -> str | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT pages.content
                FROM ingested_pages AS pages
                INNER JOIN ingested_documents AS documents
                    ON documents.id = pages.document_id
                WHERE documents.id = ? AND documents.user_id = ? AND pages.page_number = ?
                """,
                (document_id, user_id, page_number),
            ).fetchone()
        return str(row["content"]) if row else None
