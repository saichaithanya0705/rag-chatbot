from __future__ import annotations

from typing import Any, Callable

from app.core.database import Database
from app.services.document_catalog_service import DocumentCatalogService
from app.services.document_types import RetrievalChunkCatalogEntry


class DocumentChunkMetadataService:
    def __init__(
        self,
        *,
        database: Database,
        collection_getter: Callable[[], Any],
        catalog_service: DocumentCatalogService,
    ) -> None:
        self._database = database
        self._collection_getter = collection_getter
        self._catalog_service = catalog_service

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
        collection = self._collection_getter()
        chunk_rows = collection.get(include=["documents", "metadatas"])
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
            collection.update(ids=updated_ids, metadatas=updated_metadatas)
            self._catalog_service.bump_retrieval_corpus_version()
        self._catalog_service.sync_chunk_catalog(catalog_entries)

    def sync_document_chunk_metadata(self, *, document_id: str, user_id: str) -> None:
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

        collection = self._collection_getter()
        chunk_rows = collection.get(
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
            collection.update(ids=updated_ids, metadatas=updated_metadatas)

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
