from __future__ import annotations

import pytest

from app.services.chunk_store_service import ChunkStoreService


class _FakeCollection:
    def __init__(self, fetched_rows: dict[str, list[object]]) -> None:
        self.fetched_rows = fetched_rows
        self.updates: list[dict[str, object]] = []

    def get(self, *, where=None, ids=None, include=None):  # noqa: ANN001, ARG002
        if where is not None:
            return {
                "ids": ["c1", "c2"],
                "metadatas": [
                    {"user_id": "u1", "document_id": "d1"},
                    {"user_id": "u1", "document_id": "d1"},
                ],
            }
        assert ids == ["c1", "c2"]
        return self.fetched_rows

    def update(self, **kwargs: object) -> None:
        self.updates.append(kwargs)


class _FakeChromaStore:
    def __init__(self, collection: _FakeCollection) -> None:
        self.collection_instance = collection

    def collection(self, name: str):  # noqa: ANN201, ARG002
        return self.collection_instance


def _service(rows: dict[str, list[object]]) -> tuple[ChunkStoreService, _FakeCollection]:
    collection = _FakeCollection(rows)
    return (
        ChunkStoreService(chroma_store=_FakeChromaStore(collection)),  # type: ignore[arg-type]
        collection,
    )


def test_publish_uses_the_ids_in_chromas_returned_metadata_order() -> None:
    service, collection = _service(
        {
            "ids": ["c2", "c1"],
            "metadatas": [
                {"user_id": "u1", "document_id": "d1", "marker": "second"},
                {"user_id": "u1", "document_id": "d1", "marker": "first"},
            ],
        }
    )

    service.publish_chunks("d1", "u1")

    assert collection.updates[0]["ids"] == ["c2", "c1"]
    assert [metadata["marker"] for metadata in collection.updates[0]["metadatas"]] == [
        "second",
        "first",
    ]
    assert all(metadata["is_indexed"] == 1 for metadata in collection.updates[0]["metadatas"])


def test_publish_fails_if_chroma_omits_a_requested_chunk() -> None:
    service, _collection = _service(
        {
            "ids": ["c1"],
            "metadatas": [{"user_id": "u1", "document_id": "d1"}],
        }
    )

    with pytest.raises(RuntimeError, match="incomplete or mismatched"):
        service.publish_chunks("d1", "u1")


def test_publish_fails_on_cross_scope_metadata() -> None:
    service, _collection = _service(
        {
            "ids": ["c1", "c2"],
            "metadatas": [
                {"user_id": "u1", "document_id": "d1"},
                {"user_id": "other", "document_id": "d1"},
            ],
        }
    )

    with pytest.raises(RuntimeError, match="cross-scope"):
        service.publish_chunks("d1", "u1")
