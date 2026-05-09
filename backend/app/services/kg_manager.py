from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import networkx as nx


@dataclass
class TopicNodeRecord:
    collection_id: str
    display_name: str
    centroid: list[float]
    chunk_ids: list[str]
    pdf_sources: list[str]
    keyword_summary: list[str]
    page_keys: list[str]


@dataclass
class TopicSummary:
    id: str
    label: str
    chunk_count: int
    document_count: int


GRAPH_EDGE_MIN_WEIGHT = 0.45
GRAPH_MAX_NEIGHBORS_PER_TOPIC = 3


class KgManager:
    def __init__(self, kg_path: Path) -> None:
        self._legacy_pickle_path = kg_path
        self._json_path = kg_path.with_suffix(".json")
        self._lock_path = self._json_path.with_suffix(f"{self._json_path.suffix}.lock")
        self._graphs_by_user: dict[str, nx.DiGraph] = {}
        self._topics_by_user: dict[str, dict[str, TopicNodeRecord]] = {}
        self._last_loaded_signature: tuple[str, int] | None = None
        self._lock = threading.RLock()
        self._load()

    def rebuild(self, user_id: str, topics: list[TopicNodeRecord]) -> None:
        normalized_topics = self._ensure_unique_topic_labels(topics)
        graph = self._build_graph_from_topics(normalized_topics)
        topic_map = {topic.collection_id: topic for topic in normalized_topics}

        with self._lock:
            with self._storage_lock():
                self._reload_from_storage_locked()
                previous_graphs = dict(self._graphs_by_user)
                previous_topics = {
                    existing_user_id: dict(existing_topics)
                    for existing_user_id, existing_topics in self._topics_by_user.items()
                }
                self._graphs_by_user[user_id] = graph
                self._topics_by_user[user_id] = topic_map
                try:
                    self._save_locked()
                except Exception:
                    self._graphs_by_user = previous_graphs
                    self._topics_by_user = previous_topics
                    self._last_loaded_signature = self.storage_signature()
                    raise

    def storage_signature(self) -> tuple[str, int] | None:
        storage_path = self._active_storage_path()
        if storage_path is None:
            return None
        return (str(storage_path), storage_path.stat().st_mtime_ns)

    def topic_summaries(self, user_id: str) -> list[TopicSummary]:
        self._maybe_reload()
        topics = self._topics_by_user.get(user_id, {})
        return sorted(
            [
                TopicSummary(
                    id=topic.collection_id,
                    label=topic.display_name,
                    chunk_count=len(topic.chunk_ids),
                    document_count=len(topic.pdf_sources),
                )
                for topic in topics.values()
            ],
            key=lambda item: item.label.lower(),
        )

    def topic_records(self, user_id: str) -> list[TopicNodeRecord]:
        self._maybe_reload()
        return [
            TopicNodeRecord(
                collection_id=topic.collection_id,
                display_name=topic.display_name,
                centroid=list(topic.centroid),
                chunk_ids=list(topic.chunk_ids),
                pdf_sources=list(topic.pdf_sources),
                keyword_summary=list(topic.keyword_summary),
                page_keys=list(topic.page_keys),
            )
            for topic in self._topics_by_user.get(user_id, {}).values()
        ]

    def document_topic_map(self, user_id: str) -> dict[str, list[str]]:
        return {
            pdf_name: [topic["label"] for topic in topics]
            for pdf_name, topics in self.document_topic_details(user_id).items()
        }

    def document_topic_details(self, user_id: str) -> dict[str, list[dict[str, str]]]:
        self._maybe_reload()
        grouped: dict[str, list[dict[str, str]]] = {}
        for topic in self._topics_by_user.get(user_id, {}).values():
            for pdf_name in topic.pdf_sources:
                grouped.setdefault(pdf_name, [])
                if any(existing["id"] == topic.collection_id for existing in grouped[pdf_name]):
                    continue
                grouped[pdf_name].append(
                    {
                        "id": topic.collection_id,
                        "label": topic.display_name,
                    }
                )

        for pdf_name, topic_details in grouped.items():
            grouped[pdf_name] = sorted(topic_details, key=lambda item: item["label"].lower())
        return grouped

    def has_topic(self, user_id: str, collection_id: str) -> bool:
        self._maybe_reload()
        return collection_id in self._topics_by_user.get(user_id, {})

    def rank_topics(self, user_id: str, query_embedding: list[float], top_n: int = 3) -> list[str]:
        self._maybe_reload()
        topics = self._topics_by_user.get(user_id, {})
        ranked = sorted(
            topics.values(),
            key=lambda topic: self._cosine_similarity(topic.centroid, query_embedding),
            reverse=True,
        )
        return [topic.collection_id for topic in ranked[:top_n]]

    def expand_topics(
        self,
        user_id: str,
        seed_topic_ids: list[str],
        *,
        limit: int = 6,
        min_weight: float = 0.4,
    ) -> list[str]:
        self._maybe_reload()
        topics = self._topics_by_user.get(user_id, {})
        graph = self._graphs_by_user.get(user_id, nx.DiGraph())
        ordered: list[str] = []
        seen: set[str] = set()

        for topic_id in seed_topic_ids:
            if topic_id not in topics or topic_id in seen:
                continue
            ordered.append(topic_id)
            seen.add(topic_id)

        for topic_id in list(ordered):
            if len(ordered) >= limit:
                break
            if topic_id not in graph:
                continue

            outgoing_neighbors = sorted(
                graph.successors(topic_id),
                key=lambda neighbor_id: float(
                    graph.get_edge_data(topic_id, neighbor_id, default={}).get("weight", 0.0)
                ),
                reverse=True,
            )
            incoming_neighbors = sorted(
                graph.predecessors(topic_id),
                key=lambda neighbor_id: float(
                    graph.get_edge_data(neighbor_id, topic_id, default={}).get("weight", 0.0)
                ),
                reverse=True,
            )

            weighted_neighbors = [
                (
                    neighbor_id,
                    float(graph.get_edge_data(topic_id, neighbor_id, default={}).get("weight", 0.0)),
                )
                for neighbor_id in outgoing_neighbors
            ]
            weighted_neighbors.extend(
                (
                    neighbor_id,
                    float(graph.get_edge_data(neighbor_id, topic_id, default={}).get("weight", 0.0)) * 0.9,
                )
                for neighbor_id in incoming_neighbors
            )

            for neighbor_id, neighbor_weight in sorted(weighted_neighbors, key=lambda item: item[1], reverse=True):
                if len(ordered) >= limit:
                    break
                if neighbor_id in seen or neighbor_weight < min_weight:
                    continue
                ordered.append(neighbor_id)
                seen.add(neighbor_id)

        return ordered

    def graph_data(self, user_id: str) -> dict[str, list[dict[str, object]]]:
        self._maybe_reload()
        graph = self._graphs_by_user.get(user_id, nx.DiGraph())
        topics = self._topics_by_user.get(user_id, {})
        return {
            "nodes": [
                {
                    "id": topic.collection_id,
                    "label": topic.display_name,
                    "chunkCount": len(topic.chunk_ids),
                    "documentCount": len(topic.pdf_sources),
                }
                for topic in topics.values()
            ],
            "edges": [
                {
                    "source": source,
                    "target": target,
                    "weight": float(attributes.get("weight", 0.0)),
                    "directed": bool(attributes.get("directed", True)),
                }
                for source, target, attributes in graph.edges(data=True)
            ],
        }

    def _load(self) -> None:
        with self._lock:
            self._reload_from_storage_locked()

    def _reload_from_storage_locked(self) -> None:
        storage_path = self._active_storage_path()
        if storage_path is None:
            self._graphs_by_user = {}
            self._topics_by_user = {}
            self._last_loaded_signature = None
            return

        payload = self._load_json_payload(storage_path)

        graphs_by_user, topics_by_user = self._normalize_payload(payload)
        self._graphs_by_user = graphs_by_user
        self._topics_by_user = topics_by_user
        self._last_loaded_signature = (
            str(storage_path),
            storage_path.stat().st_mtime_ns,
        )

    def _save(self) -> None:
        with self._lock:
            with self._storage_lock():
                self._save_locked()

    def _save_locked(self) -> None:
        self._json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._serialize_payload()
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=self._json_path.parent,
            prefix=f"{self._json_path.stem}-",
            suffix=".tmp",
        ) as file_handle:
            json.dump(payload, file_handle, ensure_ascii=True)
            temp_path = Path(file_handle.name)
        temp_path.replace(self._json_path)
        if self._legacy_pickle_path != self._json_path:
            self._legacy_pickle_path.unlink(missing_ok=True)
        self._last_loaded_signature = (
            str(self._json_path),
            self._json_path.stat().st_mtime_ns,
        )

    @contextmanager
    def _storage_lock(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+b") as file_handle:
            file_handle.seek(0, 2)
            if file_handle.tell() == 0:
                file_handle.write(b"0")
                file_handle.flush()
            file_handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(file_handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    file_handle.seek(0)
                    msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)

    def _maybe_reload(self) -> None:
        storage_path = self._active_storage_path()
        if storage_path is None:
            if self._last_loaded_signature is not None:
                self._graphs_by_user = {}
                self._topics_by_user = {}
                self._last_loaded_signature = None
            return

        current_signature = (str(storage_path), storage_path.stat().st_mtime_ns)
        if self._last_loaded_signature == current_signature:
            return
        self._load()

    def _active_storage_path(self) -> Path | None:
        if self._json_path.exists():
            return self._json_path
        if self._legacy_pickle_path.exists():
            raise RuntimeError(
                "Legacy pickle knowledge-graph storage is no longer supported. "
                "Migrate the KG data to JSON before starting the backend."
            )
        return None

    def _load_json_payload(self, storage_path: Path) -> dict[str, object]:
        with storage_path.open("r", encoding="utf-8") as file_handle:
            return json.load(file_handle)

    def _normalize_payload(
        self,
        payload: dict[str, object],
    ) -> tuple[dict[str, nx.DiGraph], dict[str, dict[str, TopicNodeRecord]]]:
        if "graphs_by_user" in payload or "topics_by_user" in payload:
            raw_graphs = payload.get("graphs_by_user", {})
            raw_topics = payload.get("topics_by_user", {})
        else:
            raw_graphs = {"default": payload.get("graph", nx.DiGraph())}
            raw_topics = {"default": payload.get("topics", {})}

        normalized_topics = {
            str(user_id): {
                collection_id: self._topic_from_payload(topic_payload)
                for collection_id, topic_payload in dict(topic_map).items()
            }
            for user_id, topic_map in dict(raw_topics).items()
        }
        normalized_topics = {
            user_id: {
                topic.collection_id: topic
                for topic in self._ensure_unique_topic_labels(topic_map.values())
            }
            for user_id, topic_map in normalized_topics.items()
        }
        normalized_graphs = {
            user_id: self._build_graph_from_topics(topic_map.values())
            for user_id, topic_map in normalized_topics.items()
        }
        for user_id, graph_payload in dict(raw_graphs).items():
            normalized_graphs.setdefault(str(user_id), self._graph_from_payload(graph_payload))
        return normalized_graphs, normalized_topics

    def _serialize_payload(self) -> dict[str, object]:
        return {
            "graphs_by_user": {
                user_id: self._graph_to_payload(graph)
                for user_id, graph in self._graphs_by_user.items()
            },
            "topics_by_user": {
                user_id: {
                    collection_id: self._topic_to_payload(topic)
                    for collection_id, topic in topic_map.items()
                }
                for user_id, topic_map in self._topics_by_user.items()
            },
        }

    @staticmethod
    def _graph_from_payload(payload: object) -> nx.DiGraph:
        if isinstance(payload, nx.DiGraph):
            return payload
        if isinstance(payload, nx.Graph):
            return nx.DiGraph(payload)
        if not isinstance(payload, dict):
            return nx.DiGraph()

        graph = nx.DiGraph()
        for node in payload.get("nodes", []):
            node_payload = dict(node)
            node_id = str(node_payload.pop("id"))
            graph.add_node(node_id, **node_payload)
        for edge in payload.get("edges", []):
            edge_payload = dict(edge)
            source = str(edge_payload.pop("source"))
            target = str(edge_payload.pop("target"))
            graph.add_edge(source, target, **edge_payload)
        return graph

    @staticmethod
    def _graph_to_payload(graph: nx.DiGraph) -> dict[str, object]:
        return {
            "nodes": [
                {"id": node_id, **attributes}
                for node_id, attributes in graph.nodes(data=True)
            ],
            "edges": [
                {"source": source, "target": target, **attributes}
                for source, target, attributes in graph.edges(data=True)
            ],
        }

    @staticmethod
    def _topic_from_payload(payload: object) -> TopicNodeRecord:
        if isinstance(payload, TopicNodeRecord):
            return payload
        return TopicNodeRecord(**dict(payload))

    @staticmethod
    def _topic_to_payload(topic: TopicNodeRecord) -> dict[str, object]:
        return asdict(topic)

    def _edge_weight(self, left: TopicNodeRecord, right: TopicNodeRecord) -> float:
        centroid_similarity = max(self._cosine_similarity(left.centroid, right.centroid), 0.0)
        left_pages = set(left.page_keys)
        right_pages = set(right.page_keys)
        shared_pages = len(left_pages & right_pages)
        page_coverage = shared_pages / len(left_pages) if left_pages else 0.0
        left_documents = set(left.pdf_sources)
        right_documents = set(right.pdf_sources)
        shared_documents = len(left_documents & right_documents)
        document_coverage = shared_documents / len(left_documents) if left_documents else 0.0

        return 0.45 * centroid_similarity + 0.35 * page_coverage + 0.20 * document_coverage

    def _build_graph_from_topics(self, topics: list[TopicNodeRecord] | object) -> nx.DiGraph:
        topic_list = list(topics)
        graph = nx.DiGraph()

        for topic in topic_list:
            graph.add_node(
                topic.collection_id,
                label=topic.display_name,
                chunk_count=len(topic.chunk_ids),
                document_count=len(topic.pdf_sources),
            )

        for source, target, weight in self._select_graph_edges(topic_list):
            graph.add_edge(
                source,
                target,
                weight=weight,
                directed=False,
            )
        return graph

    def _ensure_unique_topic_labels(self, topics: list[TopicNodeRecord] | object) -> list[TopicNodeRecord]:
        topic_list = [
            TopicNodeRecord(
                collection_id=topic.collection_id,
                display_name=topic.display_name,
                centroid=list(topic.centroid),
                chunk_ids=list(topic.chunk_ids),
                pdf_sources=list(topic.pdf_sources),
                keyword_summary=list(topic.keyword_summary),
                page_keys=list(topic.page_keys),
            )
            for topic in topics
        ]
        label_counts: dict[str, int] = {}
        for topic in sorted(topic_list, key=lambda item: (item.display_name.lower(), item.collection_id)):
            base_label = topic.display_name.strip() or "Untitled topic"
            next_count = label_counts.get(base_label.lower(), 0) + 1
            label_counts[base_label.lower()] = next_count
            topic.display_name = base_label if next_count == 1 else f"{base_label} ({next_count})"
        return topic_list

    def _select_graph_edges(self, topics: list[TopicNodeRecord]) -> list[tuple[str, str, float]]:
        if len(topics) < 2:
            return []

        neighbor_candidates: dict[str, list[tuple[str, float]]] = {
            topic.collection_id: []
            for topic in topics
        }

        for index, left in enumerate(topics):
            for right in topics[index + 1 :]:
                forward_weight = self._edge_weight(left, right)
                reverse_weight = self._edge_weight(right, left)
                weight = max(forward_weight, reverse_weight)
                if weight < GRAPH_EDGE_MIN_WEIGHT:
                    continue
                neighbor_candidates[left.collection_id].append((right.collection_id, weight))
                neighbor_candidates[right.collection_id].append((left.collection_id, weight))

        selected_pairs: dict[tuple[str, str], float] = {}
        for source_id, candidates in neighbor_candidates.items():
            top_neighbors = sorted(candidates, key=lambda item: item[1], reverse=True)[:GRAPH_MAX_NEIGHBORS_PER_TOPIC]
            for target_id, weight in top_neighbors:
                pair_key = tuple(sorted((source_id, target_id)))
                selected_pairs[pair_key] = max(weight, selected_pairs.get(pair_key, 0.0))

        return [
            (source, target, weight)
            for (source, target), weight in sorted(
                selected_pairs.items(),
                key=lambda item: (-item[1], item[0][0], item[0][1]),
            )
        ]

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        numerator = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)
