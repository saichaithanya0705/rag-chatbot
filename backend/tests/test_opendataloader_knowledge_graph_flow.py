from __future__ import annotations

import json
from pathlib import Path
import tempfile

from chromadb.api.client import SharedSystemClient

from app.core.chroma_store import ChromaStore
from app.core.database import Database
from app.services.kg_manager import KgManager
from app.services.topic_index_service import SourceChunkRecord, TopicIndexService


class _DeterministicTopicIndexService(TopicIndexService):
    def _cluster_chunks(
        self,
        chunks: list[SourceChunkRecord],
    ) -> dict[int, list[SourceChunkRecord]]:
        groups: dict[int, list[SourceChunkRecord]] = {}
        for chunk in chunks:
            groups.setdefault(int(chunk.metadata["test_cluster"]), []).append(chunk)
        return groups


def test_opendataloader_chunk_metadata_reaches_knowledge_graph() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        database = Database(root / "state.db")
        database.initialize()
        chroma_store = ChromaStore(str(root / "chroma"))
        kg_manager = KgManager(root / "kg.pkl")
        collection = chroma_store.collection("all_chunks")

        chunk_ids = ["doc-1:1:0", "doc-1:1:1"]
        documents = [
            "Round Robin gives each process a time quantum.",
            "Scheduling tables compare preemption behavior.",
        ]
        metadatas = [
            {
                "document_id": "doc-1",
                "user_id": "user-a",
                "pdf_name": "scheduling.pdf",
                "page_number": 1,
                "chunk_index": 0,
                "is_indexed": 1,
                "parser": "opendataloader_pdf",
                "content_labels": json.dumps(["paragraph"]),
                "keywords": json.dumps(["round robin", "time quantum"]),
                "test_cluster": 0,
            },
            {
                "document_id": "doc-1",
                "user_id": "user-a",
                "pdf_name": "scheduling.pdf",
                "page_number": 1,
                "chunk_index": 1,
                "is_indexed": 1,
                "parser": "opendataloader_pdf",
                "content_labels": json.dumps(["table"]),
                "keywords": json.dumps(["scheduling table", "preemption"]),
                "test_cluster": 1,
            },
        ]
        embeddings = [[1.0, 0.0], [0.98, 0.02]]
        collection.upsert(
            ids=chunk_ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        with database.connect() as connection:
            connection.executemany(
                """
                INSERT INTO retrieval_chunks (
                    chunk_id, document_id, user_id, pdf_name, page_number,
                    chunk_index, collection_id, is_indexed, text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk_id,
                        "doc-1",
                        "user-a",
                        "scheduling.pdf",
                        1,
                        index,
                        "all_chunks",
                        1,
                        documents[index],
                    )
                    for index, chunk_id in enumerate(chunk_ids)
                ],
            )

        service = _DeterministicTopicIndexService(
            chroma_store=chroma_store,
            database=database,
            kg_manager=kg_manager,
            topic_collection_prefix="topic__",
        )
        result = service.recluster_topics(user_id="user-a")
        graph = service.graph_data(user_id="user-a")

        assert result.indexed_chunks == 2
        assert len(graph["nodes"]) == 2
        assert len(graph["edges"]) == 1
        assert {keyword for node in graph["nodes"] for keyword in node["keywords"]} == {
            "round robin",
            "time quantum",
            "scheduling table",
            "preemption",
        }
        assert all(node["sourceDocuments"] == ["scheduling.pdf"] for node in graph["nodes"])
        assert all(node["pageKeys"] == ["scheduling.pdf:1"] for node in graph["nodes"])

        projected = collection.get(ids=chunk_ids, include=["metadatas"])
        assert all(metadata["parser"] == "opendataloader_pdf" for metadata in projected["metadatas"])
        assert {metadata["content_labels"] for metadata in projected["metadatas"]} == {
            json.dumps(["paragraph"]),
            json.dumps(["table"]),
        }
        chroma_store._client._system.stop()
        SharedSystemClient.clear_system_cache()
