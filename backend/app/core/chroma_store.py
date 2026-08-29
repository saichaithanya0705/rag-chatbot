from __future__ import annotations

from typing import Any

import chromadb
from chromadb.api.types import Documents, Embeddings


class PassthroughEmbeddingFunction(chromadb.EmbeddingFunction[Documents]):
    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:
        return []


class ChromaStore:
    def __init__(self, chroma_path: str) -> None:
        self._chroma_path = chroma_path
        self._embedding_function = PassthroughEmbeddingFunction()
        self._collections: dict[str, Any] = {}
        self._client = chromadb.PersistentClient(path=self._chroma_path)

    def collection(self, name: str = "all_chunks") -> Any:
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(
                name=name,
                embedding_function=self._embedding_function,
            )
        return self._collections[name]

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
        self._collections.pop(name, None)
        try:
            self._client.delete_collection(name=name)
        except Exception:
            pass
        self._client = chromadb.PersistentClient(path=self._chroma_path)

    def reset(self) -> None:
        self._collections.clear()
        for collection_name in self.list_collection_names():
            try:
                self._client.delete_collection(collection_name)
            except Exception:
                pass
        self._client = chromadb.PersistentClient(path=self._chroma_path)
