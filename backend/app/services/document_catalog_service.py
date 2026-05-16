from __future__ import annotations

from app.core.database import Database
from app.services.document_types import RetrievalChunkCatalogEntry


class DocumentCatalogService:
    def __init__(self, *, database: Database, collection_name: str) -> None:
        self._database = database
        self._collection_name = collection_name

    def retrieval_corpus_version(self) -> int:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT version FROM retrieval_corpus_state WHERE id = 1"
            ).fetchone()
        return int(row["version"]) if row else 0

    def bump_retrieval_corpus_version(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE retrieval_corpus_state
                SET version = version + 1
                WHERE id = 1
                """
            )

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

    def sync_chunk_catalog(
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
