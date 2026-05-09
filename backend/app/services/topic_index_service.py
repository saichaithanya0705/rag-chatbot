from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering, HDBSCAN

from app.core.chroma_store import ChromaStore
from app.core.database import Database
from app.services.kg_manager import KgManager, TopicNodeRecord, TopicSummary


SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
USER_SLUG_LENGTH = 18
USER_HASH_LENGTH = 12


@dataclass
class SourceChunkRecord:
    id: str
    text: str
    embedding: list[float]
    metadata: dict[str, Any]


@dataclass
class TopicReclusterResult:
    topics: list[TopicSummary]
    document_topic_map: dict[str, list[str]]
    indexed_chunks: int
    document_count: int


class TopicIndexService:
    def __init__(
        self,
        *,
        chroma_store: ChromaStore,
        database: Database,
        kg_manager: KgManager,
        topic_collection_prefix: str,
        min_cluster_size: int = 3,
        min_samples: int = 2,
        merge_threshold: float = 0.85,
    ) -> None:
        self._chroma_store = chroma_store
        self._database = database
        self._kg_manager = kg_manager
        self._topic_collection_prefix = topic_collection_prefix
        self._min_cluster_size = min_cluster_size
        self._min_samples = min_samples
        self._merge_threshold = merge_threshold

    def list_topics(self, *, user_id: str) -> list[TopicSummary]:
        return self._kg_manager.topic_summaries(user_id)

    def document_topic_map(self, *, user_id: str) -> dict[str, list[str]]:
        return self._kg_manager.document_topic_map(user_id)

    def document_topic_details(self, *, user_id: str) -> dict[str, list[dict[str, str]]]:
        return self._kg_manager.document_topic_details(user_id)

    def graph_data(self, *, user_id: str) -> dict[str, list[dict[str, object]]]:
        return self._kg_manager.graph_data(user_id)

    def recluster_topics(self, *, user_id: str) -> TopicReclusterResult:
        source_chunks = self._load_source_chunks(user_id=user_id)

        if not source_chunks:
            self._kg_manager.rebuild(user_id, [])
            return TopicReclusterResult(
                topics=[],
                document_topic_map={},
                indexed_chunks=0,
                document_count=0,
            )

        cluster_assignments = self._cluster_chunks(source_chunks)
        topics = self._build_topics(user_id, source_chunks, cluster_assignments)
        self._update_flat_collection_metadata(source_chunks, topics)
        self._kg_manager.rebuild(user_id, topics)

        document_topic_map = self._kg_manager.document_topic_map(user_id)
        return TopicReclusterResult(
            topics=self._kg_manager.topic_summaries(user_id),
            document_topic_map=document_topic_map,
            indexed_chunks=len(source_chunks),
            document_count=len(document_topic_map),
        )

    def index_document_topics(self, *, document_id: str, user_id: str) -> TopicReclusterResult:
        new_chunks = self._load_document_chunks(document_id=document_id, user_id=user_id)
        if not new_chunks:
            document_topic_map = self._kg_manager.document_topic_map(user_id)
            return TopicReclusterResult(
                topics=self._kg_manager.topic_summaries(user_id),
                document_topic_map=document_topic_map,
                indexed_chunks=sum(
                    len(topic.chunk_ids)
                    for topic in self._kg_manager.topic_records(user_id)
                ),
                document_count=len(document_topic_map),
            )

        existing_topics = self._kg_manager.topic_records(user_id)
        if not existing_topics:
            return self.recluster_topics(user_id=user_id)
        document_chunk_prefix = f"{document_id}:"
        if any(
            chunk_id.startswith(document_chunk_prefix)
            for topic in existing_topics
            for chunk_id in topic.chunk_ids
        ):
            return self.recluster_topics(user_id=user_id)

        topic_map = {topic.collection_id: topic for topic in existing_topics}
        unassigned_chunks: list[SourceChunkRecord] = []

        for chunk in new_chunks:
            best_topic = self._best_matching_topic(chunk, topic_map.values())
            if best_topic is None:
                unassigned_chunks.append(chunk)
                continue
            self._append_chunk_to_topic(best_topic, chunk)

        if unassigned_chunks:
            cluster_assignments = self._cluster_chunks(unassigned_chunks)
            new_topics = self._build_topics(
                user_id,
                unassigned_chunks,
                cluster_assignments,
                used_collection_ids=set(topic_map),
            )
            for topic in new_topics:
                topic_map[topic.collection_id] = topic

        self._update_flat_collection_metadata(new_chunks, list(topic_map.values()))
        self._kg_manager.rebuild(user_id, list(topic_map.values()))
        document_topic_map = self._kg_manager.document_topic_map(user_id)
        return TopicReclusterResult(
            topics=self._kg_manager.topic_summaries(user_id),
            document_topic_map=document_topic_map,
            indexed_chunks=sum(len(topic.chunk_ids) for topic in topic_map.values()),
            document_count=len(document_topic_map),
        )

    def semantic_groups_for_document(
        self,
        *,
        document_id: str,
        user_id: str,
    ) -> dict[str, dict[str, str]]:
        document_chunks = self._load_document_chunks(
            document_id=document_id,
            user_id=user_id,
        )
        if not document_chunks:
            return {}

        cluster_assignments = self._cluster_chunks(document_chunks)
        semantic_groups: dict[str, dict[str, str]] = {}
        for cluster_label, members in sorted(cluster_assignments.items(), key=lambda item: item[0]):
            keyword_counter: Counter[str] = Counter()
            pdf_sources: set[str] = set()
            for chunk in members:
                keyword_counter.update(self._keywords_for_chunk(chunk))
                pdf_sources.add(str(chunk.metadata.get("pdf_name", "Unknown")))

            display_name = self._display_name_for_cluster(
                cluster_label,
                keyword_counter,
                pdf_sources,
            )
            group_id = f"{document_id}:semantic:{cluster_label + 1}"
            for chunk in members:
                semantic_groups[chunk.id] = {
                    "semantic_group": display_name,
                    "semantic_group_id": group_id,
                }

        return semantic_groups

    def remove_document_topics(self, *, document_id: str, user_id: str) -> TopicReclusterResult:
        existing_topics = self._kg_manager.topic_records(user_id)
        if not existing_topics:
            return TopicReclusterResult(
                topics=[],
                document_topic_map={},
                indexed_chunks=0,
                document_count=0,
            )

        document_chunk_prefix = f"{document_id}:"
        affected_topic_ids = {
            topic.collection_id
            for topic in existing_topics
            if any(chunk_id.startswith(document_chunk_prefix) for chunk_id in topic.chunk_ids)
        }
        if not affected_topic_ids:
            document_topic_map = self._kg_manager.document_topic_map(user_id)
            return TopicReclusterResult(
                topics=self._kg_manager.topic_summaries(user_id),
                document_topic_map=document_topic_map,
                indexed_chunks=sum(len(topic.chunk_ids) for topic in existing_topics),
                document_count=len(document_topic_map),
            )

        remaining_chunk_ids = [
            chunk_id
            for topic in existing_topics
            if topic.collection_id in affected_topic_ids
            for chunk_id in topic.chunk_ids
            if not chunk_id.startswith(document_chunk_prefix)
        ]
        chunk_lookup = {
            chunk.id: chunk
            for chunk in self._load_chunks_by_ids(remaining_chunk_ids, user_id=user_id)
        }
        updated_topics: list[TopicNodeRecord] = []

        for topic in existing_topics:
            if topic.collection_id not in affected_topic_ids:
                updated_topics.append(topic)
                continue

            remaining_topic_chunks = [
                chunk_lookup[chunk_id]
                for chunk_id in topic.chunk_ids
                if chunk_id in chunk_lookup
            ]
            if not remaining_topic_chunks:
                continue

            keyword_counter: Counter[str] = Counter()
            pdf_sources: set[str] = set()
            page_keys: set[str] = set()
            for chunk in remaining_topic_chunks:
                keyword_counter.update(self._keywords_for_chunk(chunk))
                pdf_name = str(chunk.metadata.get("pdf_name", "Unknown"))
                pdf_sources.add(pdf_name)
                page_keys.add(f"{pdf_name}:{int(chunk.metadata.get('page_number', 0))}")

            updated_topics.append(
                TopicNodeRecord(
                    collection_id=topic.collection_id,
                    display_name=topic.display_name,
                    centroid=self._mean_embedding(remaining_topic_chunks),
                    chunk_ids=[chunk.id for chunk in remaining_topic_chunks],
                    pdf_sources=sorted(pdf_sources),
                    keyword_summary=[
                        keyword
                        for keyword, _count in keyword_counter.most_common(5)
                    ],
                    page_keys=sorted(page_keys),
                )
            )

        self._kg_manager.rebuild(user_id, updated_topics)
        document_topic_map = self._kg_manager.document_topic_map(user_id)
        return TopicReclusterResult(
            topics=self._kg_manager.topic_summaries(user_id),
            document_topic_map=document_topic_map,
            indexed_chunks=sum(len(topic.chunk_ids) for topic in updated_topics),
            document_count=len(document_topic_map),
        )

    def _load_source_chunks(self, *, user_id: str) -> list[SourceChunkRecord]:
        collection = self._chroma_store.collection("all_chunks")
        rows = collection.get(
            include=["embeddings", "documents", "metadatas"],
            where={"$and": [{"user_id": user_id}, {"is_indexed": 1}]},
        )

        chunk_ids = rows.get("ids", [])
        documents = rows.get("documents", [])
        metadatas = rows.get("metadatas", [])
        embeddings = rows.get("embeddings", [])

        chunks: list[SourceChunkRecord] = []
        for chunk_id, text, metadata, embedding in zip(
            chunk_ids,
            documents,
            metadatas,
            embeddings,
            strict=False,
        ):
            chunks.append(
                SourceChunkRecord(
                    id=str(chunk_id),
                    text=str(text),
                    metadata=dict(metadata or {}),
                    embedding=[float(value) for value in embedding],
                )
            )
        return chunks

    def _load_document_chunks(self, *, document_id: str, user_id: str) -> list[SourceChunkRecord]:
        collection = self._chroma_store.collection("all_chunks")
        rows = collection.get(
            include=["embeddings", "documents", "metadatas"],
            where={"$and": [{"user_id": user_id}, {"document_id": document_id}]},
        )

        chunk_ids = rows.get("ids", [])
        documents = rows.get("documents", [])
        metadatas = rows.get("metadatas", [])
        embeddings = rows.get("embeddings", [])

        return [
            SourceChunkRecord(
                id=str(chunk_id),
                text=str(text),
                metadata=dict(metadata or {}),
                embedding=[float(value) for value in embedding],
            )
            for chunk_id, text, metadata, embedding in zip(
                chunk_ids,
                documents,
                metadatas,
                embeddings,
                strict=False,
            )
        ]

    def _load_chunks_by_ids(
        self,
        chunk_ids: list[str],
        *,
        user_id: str,
    ) -> list[SourceChunkRecord]:
        if not chunk_ids:
            return []

        rows = self._chroma_store.collection("all_chunks").get(
            ids=chunk_ids,
            include=["embeddings", "documents", "metadatas"],
        )
        return [
            SourceChunkRecord(
                id=str(chunk_id),
                text=str(text),
                metadata=dict(metadata or {}),
                embedding=[float(value) for value in embedding],
            )
            for chunk_id, text, metadata, embedding in zip(
                rows.get("ids", []),
                rows.get("documents", []),
                rows.get("metadatas", []),
                rows.get("embeddings", []),
                strict=False,
            )
            if metadata and str(metadata.get("user_id", "")).strip() == user_id
        ]

    def _clear_topic_collections(self, *, user_id: str) -> None:
        user_prefixes = self._user_topic_collection_prefixes(user_id)
        for collection_name in self._chroma_store.list_collection_names():
            if any(collection_name.startswith(prefix) for prefix in user_prefixes) or (
                user_id == "default" and self._is_legacy_topic_collection(collection_name)
            ):
                self._chroma_store.delete_collection(collection_name)

    def _cluster_chunks(self, chunks: list[SourceChunkRecord]) -> dict[int, list[SourceChunkRecord]]:
        if len(chunks) < self._min_cluster_size:
            return self._semantic_fallback_groups(chunks)

        embeddings = np.asarray([chunk.embedding for chunk in chunks], dtype=float)
        clusterer = HDBSCAN(
            min_cluster_size=self._min_cluster_size,
            min_samples=min(self._min_samples, self._min_cluster_size - 1),
            metric="euclidean",
            cluster_selection_method="eom",
        )
        labels = clusterer.fit_predict(embeddings)
        grouped = self._merge_cluster_groups(chunks, labels)

        clustered = {label: members for label, members in grouped.items() if label >= 0}
        if not clustered:
            return self._semantic_fallback_groups(chunks)

        noise_members = grouped.get(-1, [])
        if noise_members:
            fallback_start = max(clustered) + 1
            for offset, members in enumerate(self._semantic_fallback_groups(noise_members).values()):
                clustered[fallback_start + offset] = members

        return clustered

    def _merge_cluster_groups(
        self,
        chunks: list[SourceChunkRecord],
        labels: np.ndarray,
    ) -> dict[int, list[SourceChunkRecord]]:
        grouped: dict[int, list[SourceChunkRecord]] = defaultdict(list)
        for chunk, label in zip(chunks, labels, strict=False):
            grouped[int(label)].append(chunk)

        cluster_labels = [label for label in grouped if label >= 0]
        if len(cluster_labels) <= 1:
            return grouped

        parents = {label: label for label in cluster_labels}
        centroids = {
            label: self._mean_embedding(grouped[label])
            for label in cluster_labels
        }

        def find(label: int) -> int:
            while parents[label] != label:
                parents[label] = parents[parents[label]]
                label = parents[label]
            return label

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        for index, left_label in enumerate(cluster_labels):
            for right_label in cluster_labels[index + 1 :]:
                similarity = self._cosine_similarity(centroids[left_label], centroids[right_label])
                if similarity > self._merge_threshold:
                    union(left_label, right_label)

        merged: dict[int, list[SourceChunkRecord]] = defaultdict(list)
        for label, members in grouped.items():
            merged_label = -1 if label < 0 else find(label)
            merged[merged_label].extend(members)
        return merged

    def _semantic_fallback_groups(self, chunks: list[SourceChunkRecord]) -> dict[int, list[SourceChunkRecord]]:
        if not chunks:
            return {}

        if len(chunks) <= self._min_cluster_size:
            return {0: chunks}

        target_cluster_count = max(1, min(len(chunks), math.ceil(len(chunks) / self._min_cluster_size)))
        if target_cluster_count == 1:
            return {0: chunks}

        embeddings = np.asarray([chunk.embedding for chunk in chunks], dtype=float)
        try:
            labels = AgglomerativeClustering(
                n_clusters=target_cluster_count,
                metric="cosine",
                linkage="average",
            ).fit_predict(embeddings)
        except Exception:
            return self._keyword_fallback_groups(chunks)

        grouped = self._merge_cluster_groups(chunks, labels)
        clustered = {label: members for label, members in grouped.items() if label >= 0}
        if clustered:
            return {
                index: members
                for index, members in enumerate(clustered.values())
            }

        return self._keyword_fallback_groups(chunks)

    def _keyword_fallback_groups(self, chunks: list[SourceChunkRecord]) -> dict[int, list[SourceChunkRecord]]:
        grouped: dict[str, list[SourceChunkRecord]] = defaultdict(list)
        for chunk in chunks:
            keywords = self._keywords_for_chunk(chunk)
            fallback_key = keywords[0] if keywords else str(chunk.metadata.get("pdf_name", "general"))
            grouped[fallback_key].append(chunk)

        return {
            index: members
            for index, members in enumerate(grouped.values())
        }

    def _build_topics(
        self,
        user_id: str,
        source_chunks: list[SourceChunkRecord],
        cluster_assignments: dict[int, list[SourceChunkRecord]],
        used_collection_ids: set[str] | None = None,
    ) -> list[TopicNodeRecord]:
        topics: list[TopicNodeRecord] = []
        next_collection_ids = set(used_collection_ids or set())

        for cluster_label, members in sorted(cluster_assignments.items(), key=lambda item: item[0]):
            keyword_counter: Counter[str] = Counter()
            pdf_sources: set[str] = set()
            page_keys: set[str] = set()
            for chunk in members:
                keyword_counter.update(self._keywords_for_chunk(chunk))
                pdf_name = str(chunk.metadata.get("pdf_name", "Unknown"))
                pdf_sources.add(pdf_name)
                page_keys.add(f"{pdf_name}:{int(chunk.metadata.get('page_number', 0))}")

            display_name = self._display_name_for_cluster(cluster_label, keyword_counter, pdf_sources)
            collection_id = self._unique_collection_id(user_id, display_name, next_collection_ids)
            topics.append(
                TopicNodeRecord(
                    collection_id=collection_id,
                    display_name=display_name,
                    centroid=self._mean_embedding(members),
                    chunk_ids=[chunk.id for chunk in members],
                    pdf_sources=sorted(pdf_sources),
                    keyword_summary=[keyword for keyword, _count in keyword_counter.most_common(5)],
                    page_keys=sorted(page_keys),
                )
            )

        self._ensure_unique_display_names(topics)
        return topics

    def _materialize_topic_collections(
        self,
        source_chunks: list[SourceChunkRecord],
        topics: list[TopicNodeRecord],
    ) -> None:
        chunk_lookup = {chunk.id: chunk for chunk in source_chunks}

        for topic in topics:
            topic_collection = self._chroma_store.collection(topic.collection_id)
            topic_documents: list[str] = []
            topic_metadatas: list[dict[str, Any]] = []
            topic_embeddings: list[list[float]] = []

            for chunk_id in topic.chunk_ids:
                chunk = chunk_lookup[chunk_id]
                updated_metadata = {
                    **chunk.metadata,
                    "topic": topic.display_name,
                    "collection_id": topic.collection_id,
                }
                topic_documents.append(chunk.text)
                topic_metadatas.append(updated_metadata)
                topic_embeddings.append(chunk.embedding)

            topic_collection.add(
                ids=topic.chunk_ids,
                documents=topic_documents,
                metadatas=topic_metadatas,
                embeddings=topic_embeddings,
            )

    def _materialize_topic_updates(
        self,
        source_chunks: list[SourceChunkRecord],
        topic_map: dict[str, TopicNodeRecord],
    ) -> None:
        chunk_lookup = {chunk.id: chunk for chunk in source_chunks}
        chunks_by_collection: dict[str, list[SourceChunkRecord]] = defaultdict(list)

        for topic in topic_map.values():
            for chunk_id in topic.chunk_ids:
                chunk = chunk_lookup.get(chunk_id)
                if chunk is not None:
                    chunks_by_collection[topic.collection_id].append(chunk)

        for collection_id, chunks in chunks_by_collection.items():
            topic = topic_map[collection_id]
            topic_collection = self._chroma_store.collection(collection_id)
            topic_collection.add(
                ids=[chunk.id for chunk in chunks],
                documents=[chunk.text for chunk in chunks],
                metadatas=[
                    {
                        **chunk.metadata,
                        "topic": topic.display_name,
                        "collection_id": topic.collection_id,
                    }
                    for chunk in chunks
                ],
                embeddings=[chunk.embedding for chunk in chunks],
            )

    def _update_flat_collection_metadata(
        self,
        source_chunks: list[SourceChunkRecord],
        topics: list[TopicNodeRecord],
    ) -> None:
        topic_by_chunk_id = {
            chunk_id: topic
            for topic in topics
            for chunk_id in topic.chunk_ids
        }

        collection = self._chroma_store.collection("all_chunks")
        collection.update(
            ids=[chunk.id for chunk in source_chunks],
            metadatas=[
                {
                    **chunk.metadata,
                    "topic": topic_by_chunk_id[chunk.id].display_name,
                    "collection_id": topic_by_chunk_id[chunk.id].collection_id,
                }
                for chunk in source_chunks
            ],
        )
        with self._database.connect() as connection:
            connection.executemany(
                """
                UPDATE retrieval_chunks
                SET collection_id = ?
                WHERE chunk_id = ?
                """,
                [
                    (topic_by_chunk_id[chunk.id].collection_id, chunk.id)
                    for chunk in source_chunks
                ],
            )

    def _display_name_for_cluster(
        self,
        cluster_label: int,
        keyword_counter: Counter[str],
        pdf_sources: set[str],
    ) -> str:
        keyword_labels = [keyword for keyword, _count in keyword_counter.most_common(2) if keyword]
        if keyword_labels:
            return " · ".join(self._titleize(keyword) for keyword in keyword_labels)

        if pdf_sources:
            first_source = sorted(pdf_sources)[0].rsplit(".", 1)[0].replace("_", " ")
            return self._titleize(first_source)

        return f"Topic {cluster_label + 1}"

    def _keywords_for_chunk(self, chunk: SourceChunkRecord) -> list[str]:
        raw_keywords = chunk.metadata.get("keywords")
        if not raw_keywords:
            return []

        try:
            parsed = json.loads(str(raw_keywords))
        except json.JSONDecodeError:
            return []

        return [str(keyword).strip() for keyword in parsed if str(keyword).strip()]

    def _best_matching_topic(
        self,
        chunk: SourceChunkRecord,
        topics: list[TopicNodeRecord] | Any,
    ) -> TopicNodeRecord | None:
        best_topic: TopicNodeRecord | None = None
        best_score = 0.0

        for topic in topics:
            similarity = self._cosine_similarity(topic.centroid, chunk.embedding)
            if similarity > best_score:
                best_score = similarity
                best_topic = topic

        if best_topic is None or best_score < 0.55:
            return None
        return best_topic

    def _append_chunk_to_topic(self, topic: TopicNodeRecord, chunk: SourceChunkRecord) -> None:
        if chunk.id in topic.chunk_ids:
            return

        current_chunk_count = len(topic.chunk_ids)
        if current_chunk_count == 0:
            topic.centroid = list(chunk.embedding)
        else:
            topic.centroid = [
                ((existing_value * current_chunk_count) + new_value) / (current_chunk_count + 1)
                for existing_value, new_value in zip(topic.centroid, chunk.embedding, strict=False)
            ]

        topic.chunk_ids.append(chunk.id)

        pdf_name = str(chunk.metadata.get("pdf_name", "Unknown"))
        if pdf_name not in topic.pdf_sources:
            topic.pdf_sources.append(pdf_name)
            topic.pdf_sources.sort()

        page_key = f"{pdf_name}:{int(chunk.metadata.get('page_number', 0))}"
        if page_key not in topic.page_keys:
            topic.page_keys.append(page_key)
            topic.page_keys.sort()

        keyword_counter = Counter(topic.keyword_summary)
        keyword_counter.update(self._keywords_for_chunk(chunk))
        topic.keyword_summary = [
            keyword
            for keyword, _count in keyword_counter.most_common(5)
        ]

    def _unique_collection_id(self, user_id: str, display_name: str, used_collection_ids: set[str]) -> str:
        base_slug = self._slugify(display_name) or "topic"
        collection_id = f"{self._user_topic_collection_prefix(user_id)}{base_slug}"
        suffix = 2
        while collection_id in used_collection_ids:
            collection_id = f"{self._user_topic_collection_prefix(user_id)}{base_slug}-{suffix}"
            suffix += 1

        used_collection_ids.add(collection_id)
        return collection_id

    @staticmethod
    def _ensure_unique_display_names(topics: list[TopicNodeRecord]) -> None:
        label_counts: dict[str, int] = {}
        for topic in sorted(topics, key=lambda item: (item.display_name.lower(), item.collection_id)):
            base_label = topic.display_name.strip() or "Untitled topic"
            next_count = label_counts.get(base_label.lower(), 0) + 1
            label_counts[base_label.lower()] = next_count
            topic.display_name = base_label if next_count == 1 else f"{base_label} ({next_count})"

    def _user_topic_collection_prefix(self, user_id: str) -> str:
        user_slug = (self._slugify(user_id) or "default")[:USER_SLUG_LENGTH]
        user_hash = hashlib.sha1(user_id.encode("utf-8")).hexdigest()[:USER_HASH_LENGTH]
        return f"{self._topic_collection_prefix}user-{user_slug}-{user_hash}__"

    def _user_topic_collection_prefixes(self, user_id: str) -> tuple[str, ...]:
        legacy_slug = self._slugify(user_id) or "default"
        legacy_prefix = f"{self._topic_collection_prefix}user-{legacy_slug}__"
        return (
            self._user_topic_collection_prefix(user_id),
            legacy_prefix,
        )

    def _is_legacy_topic_collection(self, collection_name: str) -> bool:
        if not collection_name.startswith(self._topic_collection_prefix):
            return False
        remainder = collection_name[len(self._topic_collection_prefix) :]
        return "__" not in remainder

    @staticmethod
    def _mean_embedding(chunks: list[SourceChunkRecord]) -> list[float]:
        if not chunks:
            return []

        width = len(chunks[0].embedding)
        totals = [0.0] * width
        for chunk in chunks:
            for index, value in enumerate(chunk.embedding):
                totals[index] += value

        return [value / len(chunks) for value in totals]

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = SLUG_PATTERN.sub("-", value.lower()).strip("-")
        return normalized

    @staticmethod
    def _titleize(value: str) -> str:
        return " ".join(word.capitalize() for word in value.replace("-", " ").split())

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        numerator = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)
