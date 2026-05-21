from __future__ import annotations

from typing import Any

import chromadb


class ChromaStore:
    def __init__(self, chroma_path: str) -> None:
        self._client = chromadb.PersistentClient(path=chroma_path)

    def collection(self, name: str = "all_chunks") -> Any:
        return self._client.get_or_create_collection(name=name)

    @property
    def max_batch_size(self) -> int | None:
        value = getattr(self._client, "max_batch_size", None)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def list_collection_names(self) -> list[str]:
        return [collection.name for collection in self._client.list_collections()]

    def has_collections(self) -> bool:
        return bool(self.list_collection_names())

    def delete_collection(self, name: str) -> None:
        self._client.delete_collection(name=name)

    def reset(self) -> None:
        for collection_name in self.list_collection_names():
            self.delete_collection(collection_name)
