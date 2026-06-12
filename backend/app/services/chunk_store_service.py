from __future__ import annotations

from typing import Any

from app.core.chroma_store import ChromaStore
from app.services.document_types import StoredChunk


class ChunkStoreService:
    """Manages chunk storage and retrieval from vector store (Chroma).
    
    Responsibility: Encapsulate vector store operations (get, update, delete, query).
    Does not own chunk metadata persistence or publication logic.
    """

    def __init__(
        self,
        *,
        chroma_store: ChromaStore,
        collection_name: str = "all_chunks",
    ) -> None:
        self._chroma_store = chroma_store
        self._collection_name = collection_name

    def collection(self) -> Any:
        return self._chroma_store.collection(self._collection_name)

    def get_chunk(
        self,
        pdf_name: str | None,
        page_number: int,
        chunk_index: int,
        *,
        document_id: str | None = None,
        user_id: str,
    ) -> StoredChunk | None:
        """Retrieve a single chunk by document/page/index."""
        where_clauses: list[dict[str, object]] = [
            {"user_id": user_id},
            {"page_number": page_number},
            {"chunk_index": chunk_index},
        ]
        if document_id:
            where_clauses.append({"document_id": document_id})
        elif pdf_name is not None:
            where_clauses.append({"pdf_name": pdf_name})

        result = self.collection().get(
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

    def get_chunks_for_document(
        self,
        document_id: str,
        user_id: str,
    ) -> list[str]:
        """Get all chunk IDs for a document."""
        rows = self.collection().get(
            where={"$and": [{"document_id": document_id}, {"user_id": user_id}]},
            include=["metadatas"],
        )
        return [str(chunk_id) for chunk_id in rows.get("ids", [])]

    def publish_chunks(
        self,
        document_id: str,
        user_id: str,
    ) -> None:
        """Mark all chunks for a document as indexed."""
        chunk_ids = self.get_chunks_for_document(document_id, user_id)
        if not chunk_ids:
            return

        updated_metadatas = [
            {**dict(metadata or {}), "is_indexed": 1}
            for metadata in self.collection().get(
                where={"$and": [{"document_id": document_id}, {"user_id": user_id}]},
                include=["metadatas"],
            ).get("metadatas", [])
        ]
        
        # Batch updates to respect Chroma's max batch size constraint (5461)
        batch_size = 2000
        for i in range(0, len(chunk_ids), batch_size):
            batch_ids = chunk_ids[i : i + batch_size]
            batch_metadatas = updated_metadatas[i : i + batch_size]
            self.collection().update(ids=batch_ids, metadatas=batch_metadatas)

    def delete_chunks_for_document(
        self,
        document_id: str,
        user_id: str,
    ) -> None:
        """Delete all chunks for a document."""
        self.collection().delete(where={"$and": [{"document_id": document_id}, {"user_id": user_id}]})
