from __future__ import annotations

import logging
from pathlib import Path

from app.core.chroma_store import ChromaStore
from app.core.database import Database, EmbeddingIndexState


LOGGER = logging.getLogger(__name__)


class EmbeddingIndexService:
    """Keeps persisted vector state aligned with the active embedding model."""

    def __init__(
        self,
        *,
        database: Database,
        chroma_store: ChromaStore,
        kg_path: Path,
        model: str,
        dimensions: int,
    ) -> None:
        self._database = database
        self._chroma_store = chroma_store
        self._kg_path = kg_path
        self._model = model.strip()
        self._dimensions = dimensions

    def reconcile(self) -> None:
        previous_state = self._database.get_embedding_index_state()
        if self._requires_reset(previous_state):
            LOGGER.warning(
                "Embedding index contract changed to %s (%s dimensions); resetting vector-backed state.",
                self._model,
                self._dimensions,
            )
            self._chroma_store.reset()
            self._database.reset_embedding_backed_state()
            self._delete_knowledge_graph_storage()

        self._database.set_embedding_index_state(
            model=self._model,
            dimensions=self._dimensions,
        )

    def _requires_reset(self, previous_state: EmbeddingIndexState | None) -> bool:
        if previous_state is None:
            return (
                self._database.has_embedding_backed_state()
                or self._chroma_store.has_collections()
                or self._has_knowledge_graph_storage()
            )
        return not self._matches(previous_state)

    def _matches(self, state: EmbeddingIndexState) -> bool:
        return state.model == self._model and state.dimensions == self._dimensions

    def _has_knowledge_graph_storage(self) -> bool:
        return any(path.exists() for path in self._knowledge_graph_storage_paths())

    def _delete_knowledge_graph_storage(self) -> None:
        for path in self._knowledge_graph_storage_paths():
            path.unlink(missing_ok=True)

    def _knowledge_graph_storage_paths(self) -> tuple[Path, Path]:
        return (self._kg_path, self._kg_path.with_suffix(".json"))
