from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Sequence

from app.core.chroma_store import ChromaStore
from app.services.document_service import DocumentService
from app.services.kg_manager import KgManager
from app.services.rag_answer_text import (
    DIRECT_QA_MATCH_THRESHOLD,
    extract_direct_qa_pair,
    first_sentence,
    is_informative_answer_sentence,
    question_match_score,
    shape_shortcut_answer,
    tokenize,
)
from app.services.rag_citations import (
    docling_source_metadata_from_metadata,
    pdf_context_from_chunk,
    retrieved_chunk_from_candidate,
)
from app.services.rag_comparison import (
    comparison_question_score,
    comparison_search_query,
    comparison_subqueries,
)
from app.services.rag_grounding import CONTEXT_FALLBACK_CHAR_LIMIT, clean_context_snippet, normalize_context_text
from app.services.rag_types import CandidateChunk, RetrievalResult, RetrievedContext
from app.services.reranker_service import RerankerService
from app.services.web_search_service import WebSearchResult


RRF_K = 60
MIN_TOPIC_RETRIEVAL_CANDIDATES = 5
MIN_INTERACTIVE_RERANK_CANDIDATES = 6
MAX_INTERACTIVE_RERANK_CANDIDATES = 8
DOMINANT_RESULT_SHARE = 0.75
FUSED_SCORE_DOMINANCE_MARGIN = 0.01
LOGGER = logging.getLogger(__name__)


class RagRetrievalEngine:
    def __init__(
        self,
        *,
        chroma_store: ChromaStore,
        document_service: DocumentService,
        kg_manager: KgManager,
        reranker_service: RerankerService,
        collection_name: str = "all_chunks",
        top_k: int,
        web_search_score_threshold: float,
    ) -> None:
        self._chroma_store = chroma_store
        self._document_service = document_service
        self._kg_manager = kg_manager
        self._reranker_service = reranker_service
        self._collection_name = collection_name
        self._top_k = top_k
        self._web_search_score_threshold = web_search_score_threshold

    @property
    def top_k(self) -> int:
        return self._top_k

    def retrieve_chunks(
        self,
        question: str,
        query_embedding: list[float],
        collection_id: str,
        *,
        user_id: str,
    ) -> RetrievalResult:
        target_collections = self._resolve_target_collections(query_embedding, collection_id, user_id=user_id)
        candidate_map: dict[str, CandidateChunk] = {}

        for target_collection in target_collections:
            for candidate in self._hybrid_candidates_for_collection(
                question,
                query_embedding,
                target_collection,
                user_id=user_id,
            ):
                existing = candidate_map.get(candidate.chunk_id)
                if existing is None or candidate.fused_score > existing.fused_score:
                    candidate_map[candidate.chunk_id] = candidate

        include_flat = self._should_query_flat_collection(
            collection_id=collection_id,
            target_collections=target_collections,
            candidate_count=len(candidate_map),
        )
        if include_flat:
            for candidate in self._hybrid_candidates_for_collection(
                question,
                query_embedding,
                self._collection_name,
                user_id=user_id,
            ):
                existing = candidate_map.get(candidate.chunk_id)
                if existing is None or candidate.fused_score > existing.fused_score:
                    candidate_map[candidate.chunk_id] = candidate

        scoped_collection_names = list(target_collections)
        if include_flat and self._collection_name not in scoped_collection_names:
            scoped_collection_names.append(self._collection_name)

        self._merge_comparison_lexical_candidates(
            candidate_map,
            question=question,
            collection_names=scoped_collection_names,
            user_id=user_id,
        )

        if not candidate_map:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        fused_candidates = sorted(
            candidate_map.values(),
            key=lambda chunk: chunk.fused_score,
            reverse=True,
        )
        rerank_pool_limit = self._rerank_pool_limit(
            question=question,
            ordered_candidates=fused_candidates,
        )
        fused_candidates = self._select_rerank_candidate_pool(
            question=question,
            ordered_candidates=fused_candidates,
            collection_names=scoped_collection_names,
            user_id=user_id,
            limit=rerank_pool_limit,
        )
        ranked_candidates = self._rank_candidates(
            question=question,
            ordered_candidates=fused_candidates,
        )
        selected_chunks = self._select_final_chunks(
            question=question,
            ranked_candidates=ranked_candidates,
            collection_names=scoped_collection_names,
            user_id=user_id,
        )

        return RetrievalResult(
            chunks=[
                retrieved_chunk_from_candidate(candidate)
                for candidate in selected_chunks
            ],
            top_rerank_score=selected_chunks[0].rerank_score if selected_chunks else None,
        )

    def retrieve_chunks_without_embedding(
        self,
        question: str,
        collection_id: str,
        *,
        user_id: str,
    ) -> RetrievalResult:
        target_collection = self._collection_name if collection_id == "all-pdfs" else collection_id
        candidates = self._lexical_candidates_for_collection(
            question,
            target_collection,
            user_id=user_id,
            limit=max(self._top_k * 4, 16),
        )
        candidate_map = {candidate.chunk_id: candidate for candidate in candidates}
        self._merge_comparison_lexical_candidates(
            candidate_map,
            question=question,
            collection_names=[target_collection],
            user_id=user_id,
        )
        candidates = sorted(
            candidate_map.values(),
            key=lambda candidate: candidate.fused_score,
            reverse=True,
        )
        rerank_pool_limit = self._rerank_pool_limit(
            question=question,
            ordered_candidates=candidates,
        )
        candidates = self._select_rerank_candidate_pool(
            question=question,
            ordered_candidates=candidates,
            collection_names=[target_collection],
            user_id=user_id,
            limit=rerank_pool_limit,
        )
        if not candidates:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        for rank, candidate in enumerate(candidates):
            candidate.fused_score = self._rrf_score(rank)

        ranked_candidates = self._rank_candidates(
            question=question,
            ordered_candidates=candidates,
        )
        selected_chunks = self._select_final_chunks(
            question=question,
            ranked_candidates=ranked_candidates,
            collection_names=[target_collection],
            user_id=user_id,
        )

        return RetrievalResult(
            chunks=[
                retrieved_chunk_from_candidate(candidate)
                for candidate in selected_chunks
            ],
            top_rerank_score=selected_chunks[0].rerank_score if selected_chunks else None,
        )

    def fallback_chunks(
        self,
        question: str,
        query_embedding: list[float],
        *,
        user_id: str,
    ) -> RetrievalResult:
        all_chunks = self._hybrid_candidates_for_collection(
            question,
            query_embedding,
            self._collection_name,
            user_id=user_id,
        )
        if not all_chunks:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        rerank_scores = self._reranker_service.score_pairs(
            question,
            [candidate.text for candidate in all_chunks],
        )
        for candidate, score in zip(all_chunks, rerank_scores, strict=False):
            candidate.rerank_score = score

        reranked = sorted(
            all_chunks,
            key=lambda chunk: (
                chunk.rerank_score if chunk.rerank_score is not None else float("-inf"),
                chunk.fused_score,
            ),
            reverse=True,
        )[: self._top_k]

        return RetrievalResult(
            chunks=[
                retrieved_chunk_from_candidate(candidate)
                for candidate in reranked
            ],
            top_rerank_score=reranked[0].rerank_score if reranked else None,
        )

    def comparison_contexts(
        self,
        question: str,
        *,
        collection_id: str,
        user_id: str,
    ) -> list[RetrievedContext]:
        subqueries = comparison_subqueries(question)
        if len(subqueries) < 2:
            return []

        target_collection = self._collection_name if collection_id == "all-pdfs" else collection_id
        contexts: list[RetrievedContext] = []
        seen_ids: set[str] = set()
        comparison_limit = max(self._top_k * 4, 10)
        for subquery in subqueries:
            search_query = comparison_search_query(subquery)
            lookup_query = (
                search_query
                if search_query.lower().startswith("what ")
                else f"what is {search_query}"
            )
            candidate_map: dict[str, CandidateChunk] = {}
            candidate_queries = [subquery]
            if search_query.lower() != subquery.lower():
                candidate_queries.append(search_query)
            if lookup_query.lower() not in {query.lower() for query in candidate_queries}:
                candidate_queries.append(lookup_query)

            for candidate_query in candidate_queries:
                for candidate in self._lexical_candidates_for_collection(
                    candidate_query,
                    target_collection,
                    user_id=user_id,
                    limit=comparison_limit,
                ):
                    candidate_map.setdefault(candidate.chunk_id, candidate)

            candidates = list(candidate_map.values())
            if not candidates:
                continue

            question_matched_pool = [
                candidate
                for candidate in candidates
                if comparison_question_score(subquery, candidate) > 0
            ] or candidates
            preferred_pool = [
                candidate
                for candidate in question_matched_pool
                if self._candidate_has_standalone_answer(candidate)
            ] or question_matched_pool

            rerank_scores = self._reranker_service.score_pairs(
                lookup_query,
                [candidate.text for candidate in preferred_pool],
            )
            best_index = max(
                range(len(preferred_pool)),
                key=lambda index: (
                    comparison_question_score(subquery, preferred_pool[index]),
                    1 if self._candidate_has_standalone_answer(preferred_pool[index]) else 0,
                    rerank_scores[index] if index < len(rerank_scores) else float("-inf"),
                ),
            )
            preferred_candidate = preferred_pool[best_index]
            if preferred_candidate is None or preferred_candidate.chunk_id in seen_ids:
                continue
            seen_ids.add(preferred_candidate.chunk_id)
            contexts.append(
                pdf_context_from_chunk(retrieved_chunk_from_candidate(preferred_candidate))
            )

        return contexts

    def direct_lexical_shortcut(
        self,
        question: str,
        *,
        collection_id: str,
        user_id: str,
    ) -> tuple[RetrievedContext, str] | None:
        lexical_contexts = [
            pdf_context_from_chunk(retrieved_chunk_from_candidate(candidate))
            for candidate in self._lexical_candidates_for_collection(
                question,
                self._collection_name if collection_id == "all-pdfs" else collection_id,
                user_id=user_id,
                limit=max(self._top_k * 4, 12),
            )
        ]
        best_match: tuple[tuple[int, float, int], RetrievedContext, str] | None = None
        for context in lexical_contexts:
            qa_pair = extract_direct_qa_pair(context.text)
            if qa_pair is None:
                continue
            qa_question, qa_answer = qa_pair
            match_score = question_match_score(question, qa_question)
            if match_score < DIRECT_QA_MATCH_THRESHOLD:
                continue
            cleaned_answer = clean_context_snippet(
                qa_answer,
                max_chars=CONTEXT_FALLBACK_CHAR_LIMIT * 2,
            )
            if not cleaned_answer:
                continue
            cleaned_answer = shape_shortcut_answer(question, cleaned_answer)
            candidate_rank = (
                1 if is_informative_answer_sentence(first_sentence(cleaned_answer)) else 0,
                match_score,
                len(tokenize(cleaned_answer)),
            )
            if best_match is None or candidate_rank > best_match[0]:
                best_match = (candidate_rank, context, cleaned_answer)
        if best_match is None:
            return None
        _rank, best_context, best_answer = best_match
        return best_context, best_answer

    def web_contexts_from_results(self, results: list[WebSearchResult]) -> list[RetrievedContext]:
        return [
            RetrievedContext(
                id=f"web:{index}:{result.url}",
                kind="web",
                label=f"[Web: {result.url}]",
                text="\n".join(
                    part
                    for part in (
                        result.title,
                        f"Published: {result.published_at}" if result.published_at else None,
                        result.content,
                    )
                    if part
                ),
                excerpt=result.content[:280],
                url=result.url,
                title=result.title,
            )
            for index, result in enumerate(results)
        ]

    def rerank_web_results(
        self,
        query: str,
        results: list[WebSearchResult],
    ) -> list[WebSearchResult]:
        if not results:
            return []

        passages = [
            "\n".join(part for part in (result.title, result.snippet, result.content[:1600]) if part)
            for result in results
        ]
        rerank_scores = self._reranker_service.score_pairs(query, passages)
        scored_results = []
        for result, rerank_score in zip(results, rerank_scores, strict=False):
            freshness_bonus = self._web_result_freshness_bonus(query, result)
            scored_results.append((rerank_score + freshness_bonus, result))

        scored_results.sort(key=lambda item: item[0], reverse=True)
        return [result for _score, result in scored_results]

    def should_use_web_search(self, top_rerank_score: float | None) -> bool:
        if top_rerank_score is None:
            return False
        return top_rerank_score < self._web_search_score_threshold

    def has_local_context(self, collection_id: str, *, user_id: str) -> bool:
        if collection_id == "all-pdfs":
            return self._document_service.count_indexed_chunks(user_id=user_id) > 0

        for topic in self._kg_manager.topic_summaries(user_id):
            if topic.id == collection_id:
                return topic.chunk_count > 0
        return False

    def _should_query_flat_collection(
        self,
        *,
        collection_id: str,
        target_collections: list[str],
        candidate_count: int,
    ) -> bool:
        if collection_id != "all-pdfs":
            return False
        if self._collection_name in target_collections:
            return False
        if not target_collections:
            return True
        return candidate_count < max(self._top_k, MIN_TOPIC_RETRIEVAL_CANDIDATES)

    def _resolve_target_collections(
        self,
        query_embedding: list[float],
        collection_id: str,
        *,
        user_id: str,
    ) -> list[str]:
        if collection_id != "all-pdfs":
            return [collection_id] if self._kg_manager.has_topic(user_id, collection_id) else []

        seed_topics = self._kg_manager.rank_topics(user_id, query_embedding, top_n=3)
        return self._kg_manager.expand_topics(user_id, seed_topics, limit=6, min_weight=0.4)

    def _hybrid_candidates_for_collection(
        self,
        question: str,
        query_embedding: list[float],
        collection_id: str,
        *,
        user_id: str,
    ) -> list[CandidateChunk]:
        limit = max(self._top_k * 2, 8)
        vector_candidates = {
            candidate.chunk_id: candidate
            for candidate in self._vector_candidates_for_collection(
                query_embedding,
                collection_id,
                user_id=user_id,
                limit=limit,
            )
        }

        candidates = dict(vector_candidates)
        for rank, lexical_candidate in enumerate(
            self._lexical_candidates_for_collection(
                question,
                collection_id,
                user_id=user_id,
                limit=limit,
            )
        ):
            chunk_id = lexical_candidate.chunk_id
            candidate = candidates.get(chunk_id)
            if candidate is None:
                candidate = lexical_candidate
                candidates[chunk_id] = candidate
            candidate.fused_score += self._rrf_score(rank)

        return list(candidates.values())

    def _lexical_candidates_for_collection(
        self,
        question: str,
        collection_id: str,
        *,
        user_id: str,
        limit: int,
    ) -> list[CandidateChunk]:
        fts_query = self._build_fts_query(question)
        if not fts_query:
            return []

        rows = self._document_service.search_chunk_catalog(
            query=fts_query,
            collection_id=collection_id,
            user_id=user_id,
            limit=limit,
        )
        metadata_by_chunk_id = self._metadata_by_chunk_id([row.chunk_id for row in rows])
        return [
            CandidateChunk(
                chunk_id=row.chunk_id,
                collection_id=row.collection_id or collection_id,
                document_id=row.document_id,
                pdf_name=row.pdf_name,
                page_number=row.page_number,
                chunk_index=row.chunk_index,
                text=row.text,
                **docling_source_metadata_from_metadata(
                    metadata_by_chunk_id.get(row.chunk_id, {})
                ),
            )
            for row in rows
        ]

    def _metadata_by_chunk_id(self, chunk_ids: Sequence[str]) -> dict[str, dict[str, object]]:
        if not chunk_ids:
            return {}
        try:
            rows = self._chroma_store.collection(self._collection_name).get(
                ids=list(chunk_ids),
                include=["metadatas"],
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning("Could not load chunk metadata for lexical citations.", exc_info=True)
            return {}

        return {
            str(chunk_id): dict(metadata or {})
            for chunk_id, metadata in zip(
                rows.get("ids", []),
                rows.get("metadatas", []),
                strict=False,
            )
        }

    def _merge_comparison_lexical_candidates(
        self,
        candidate_map: dict[str, CandidateChunk],
        *,
        question: str,
        collection_names: Sequence[str],
        user_id: str,
    ) -> None:
        subqueries = comparison_subqueries(question)
        if not subqueries:
            return

        unique_collections = list(dict.fromkeys(collection_names))
        for subquery in subqueries:
            for collection_name in unique_collections:
                for rank, candidate in enumerate(
                    self._lexical_candidates_for_collection(
                        subquery,
                        collection_name,
                        user_id=user_id,
                        limit=max(self._top_k, 4),
                    )
                ):
                    bonus = self._rrf_score(rank) * 0.75
                    existing = candidate_map.get(candidate.chunk_id)
                    if existing is None:
                        candidate.fused_score = bonus
                        candidate_map[candidate.chunk_id] = candidate
                    else:
                        existing.fused_score += bonus

    def _select_final_chunks(
        self,
        *,
        question: str,
        ranked_candidates: Sequence[CandidateChunk],
        collection_names: Sequence[str],
        user_id: str,
    ) -> list[CandidateChunk]:
        coverage_groups = self._comparison_hit_groups(
            question=question,
            collection_names=collection_names,
            user_id=user_id,
        )
        if not coverage_groups:
            return list(ranked_candidates[: self._top_k])

        selected: list[CandidateChunk] = []
        selected_ids: set[str] = set()
        for hit_ids in coverage_groups:
            for candidate in ranked_candidates:
                if candidate.chunk_id not in hit_ids or candidate.chunk_id in selected_ids:
                    continue
                selected.append(candidate)
                selected_ids.add(candidate.chunk_id)
                break

        for candidate in ranked_candidates:
            if candidate.chunk_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.chunk_id)
            if len(selected) >= self._top_k:
                break

        return selected[: self._top_k]

    def _select_rerank_candidate_pool(
        self,
        *,
        question: str,
        ordered_candidates: Sequence[CandidateChunk],
        collection_names: Sequence[str],
        user_id: str,
        limit: int,
    ) -> list[CandidateChunk]:
        if not ordered_candidates:
            return []

        selected = list(ordered_candidates[:limit])
        selected_ids = {candidate.chunk_id for candidate in selected}
        for hit_ids in self._comparison_hit_groups(
            question=question,
            collection_names=collection_names,
            user_id=user_id,
        ):
            if any(candidate.chunk_id in hit_ids for candidate in selected):
                continue
            for candidate in ordered_candidates:
                if candidate.chunk_id not in hit_ids or candidate.chunk_id in selected_ids:
                    continue
                selected.append(candidate)
                selected_ids.add(candidate.chunk_id)
                break

        return selected

    def _rerank_pool_limit(
        self,
        *,
        question: str,
        ordered_candidates: Sequence[CandidateChunk],
    ) -> int:
        if not ordered_candidates:
            return 0
        if comparison_subqueries(question):
            return min(len(ordered_candidates), max(self._top_k * 2, MAX_INTERACTIVE_RERANK_CANDIDATES))
        return min(
            len(ordered_candidates),
            max(self._top_k + 1, MIN_INTERACTIVE_RERANK_CANDIDATES),
        )

    def _should_rerank_candidates(
        self,
        *,
        question: str,
        ordered_candidates: Sequence[CandidateChunk],
    ) -> bool:
        if len(ordered_candidates) <= 1:
            return False
        if comparison_subqueries(question):
            return True

        top_window = list(ordered_candidates[: max(self._top_k, 4)])
        if len(top_window) <= 1:
            return False

        fused_margin = top_window[0].fused_score - top_window[-1].fused_score
        if fused_margin >= FUSED_SCORE_DOMINANCE_MARGIN:
            return False

        dominant_document_count = Counter(candidate.document_id for candidate in top_window).most_common(1)[0][1]
        if dominant_document_count / len(top_window) >= DOMINANT_RESULT_SHARE:
            return False

        collection_counts = Counter(
            candidate.collection_id
            for candidate in top_window
            if candidate.collection_id
        )
        if collection_counts:
            dominant_collection_count = collection_counts.most_common(1)[0][1]
            if dominant_collection_count / len(top_window) >= DOMINANT_RESULT_SHARE:
                return False

        return True

    def _rank_candidates(
        self,
        *,
        question: str,
        ordered_candidates: Sequence[CandidateChunk],
    ) -> list[CandidateChunk]:
        ranked_candidates = list(ordered_candidates)
        if not ranked_candidates or not self._should_rerank_candidates(
            question=question,
            ordered_candidates=ranked_candidates,
        ):
            return ranked_candidates

        rerank_scores = self._reranker_service.score_pairs(
            question,
            [candidate.text for candidate in ranked_candidates],
        )
        for candidate, score in zip(ranked_candidates, rerank_scores, strict=False):
            candidate.rerank_score = score

        return sorted(
            ranked_candidates,
            key=lambda chunk: (
                chunk.rerank_score if chunk.rerank_score is not None else float("-inf"),
                chunk.fused_score,
            ),
            reverse=True,
        )

    def _comparison_hit_groups(
        self,
        *,
        question: str,
        collection_names: Sequence[str],
        user_id: str,
    ) -> list[set[str]]:
        subqueries = comparison_subqueries(question)
        if not subqueries:
            return []

        unique_collections = list(dict.fromkeys(collection_names))
        groups: list[set[str]] = []
        for subquery in subqueries:
            hit_ids: set[str] = set()
            for collection_name in unique_collections:
                hit_ids.update(
                    candidate.chunk_id
                    for candidate in self._lexical_candidates_for_collection(
                        subquery,
                        collection_name,
                        user_id=user_id,
                        limit=max(self._top_k, 4),
                    )
                )
            if hit_ids:
                groups.append(hit_ids)
        return groups

    def _candidate_has_standalone_answer(self, candidate: CandidateChunk) -> bool:
        qa_pair = extract_direct_qa_pair(candidate.text)
        if qa_pair is None:
            return False
        return is_informative_answer_sentence(first_sentence(qa_pair[1]))

    def _vector_candidates_for_collection(
        self,
        query_embedding: list[float],
        collection_id: str,
        *,
        user_id: str,
        limit: int,
    ) -> list[CandidateChunk]:
        collection = self._chroma_store.collection(self._collection_name)
        where_filter = self._where_filter(collection_id, user_id=user_id)
        vector_rows = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        candidates: list[CandidateChunk] = []
        for rank, (chunk_id, text, metadata) in enumerate(
            zip(
                vector_rows.get("ids", [[]])[0],
                vector_rows.get("documents", [[]])[0],
                vector_rows.get("metadatas", [[]])[0],
                strict=False,
            ),
        ):
            candidates.append(
                CandidateChunk(
                    chunk_id=str(chunk_id),
                    collection_id=collection_id,
                    document_id=str(metadata["document_id"]),
                    pdf_name=str(metadata["pdf_name"]),
                    page_number=int(metadata["page_number"]),
                    chunk_index=int(metadata["chunk_index"]),
                    text=str(text),
                    fused_score=self._rrf_score(rank),
                    **docling_source_metadata_from_metadata(dict(metadata or {})),
                )
            )
        return candidates

    @staticmethod
    def _build_fts_query(text: str) -> str:
        tokens = tokenize(text)
        if not tokens:
            return ""
        unique_tokens: list[str] = []
        seen_tokens: set[str] = set()
        for token in tokens:
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            unique_tokens.append(token)
        return " OR ".join(f'"{token}"' for token in unique_tokens)

    @staticmethod
    def _rrf_score(rank: int) -> float:
        return 1.0 / (RRF_K + rank + 1)

    @staticmethod
    def _web_result_freshness_bonus(query: str, result: WebSearchResult) -> float:
        bonus = 0.0
        query_text = query.lower()
        result_text = f"{result.title} {result.snippet}".lower()
        current_intent = any(
            token in query_text
            for token in ("latest", "current", "today", "recent", "new", "stable", "version", "release")
        )

        if current_intent and any(
            token in result_text
            for token in ("latest", "current", "stable", "release notes", "changelog", "version")
        ):
            bonus += 0.12

        if result.published_at:
            year_match = re.search(r"(20\d{2})", result.published_at)
            if year_match:
                current_year = datetime.now(UTC).year
                year = int(year_match.group(1))
                if year >= current_year:
                    bonus += 0.16
                elif year == current_year - 1:
                    bonus += 0.08
                elif current_intent:
                    bonus -= min(0.12, 0.03 * max(current_year - year - 1, 0))

        return bonus

    def _where_filter(self, collection_id: str, *, user_id: str) -> dict[str, object]:
        if collection_id == self._collection_name:
            return {"$and": [{"user_id": user_id}, {"is_indexed": 1}]}
        return {
            "$and": [
                {"user_id": user_id},
                {"is_indexed": 1},
                {"collection_id": collection_id},
            ]
        }
