from __future__ import annotations

from typing import Any

import chromadb
from chromadb.api.types import Documents, Embeddings


class ExplicitEmbeddingFunction(chromadb.EmbeddingFunction[Documents]):
    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:
        raise RuntimeError(
            "This application requires callers to provide explicit embeddings for every Chroma operation."
        )

    @staticmethod
    def name() -> str:
        return "rag-explicit-embeddings"

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "ExplicitEmbeddingFunction":
        del config
        return ExplicitEmbeddingFunction()

    def get_config(self) -> dict[str, Any]:
        return {}


class ChromaStore:
    def __init__(self, chroma_path: str) -> None:
        self._chroma_path = chroma_path
        self._embedding_function = ExplicitEmbeddingFunction()
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
        self._client.delete_collection(name=name)
        self._client = chromadb.PersistentClient(path=self._chroma_path)

    def reset(self) -> None:
        self._collections.clear()
        for collection_name in self.list_collection_names():
            self._client.delete_collection(collection_name)
        self._client = chromadb.PersistentClient(path=self._chroma_path)
