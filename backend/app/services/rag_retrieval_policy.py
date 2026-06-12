from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from app.services.rag_answer_text import tokenize
from app.services.rag_comparison import comparison_subqueries
from app.services.rag_types import CandidateChunk


RRF_K = 60
MIN_TOPIC_RETRIEVAL_CANDIDATES = 5
MIN_INTERACTIVE_RERANK_CANDIDATES = 6
MAX_INTERACTIVE_RERANK_CANDIDATES = 8
DOMINANT_RESULT_SHARE = 0.75
FUSED_SCORE_DOMINANCE_MARGIN = 0.01


def should_query_flat_collection(
    *,
    collection_id: str,
    target_collections: Sequence[str],
    candidate_count: int,
    collection_name: str,
    top_k: int,
) -> bool:
    if collection_id != "all-pdfs":
        return False
    if collection_name in target_collections:
        return False
    if not target_collections:
        return True
    return candidate_count < max(top_k, MIN_TOPIC_RETRIEVAL_CANDIDATES)


def build_fts_query(text: str) -> str:
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


def rrf_score(rank: int) -> float:
    return 1.0 / (RRF_K + rank + 1)


def rerank_pool_limit(
    *,
    question: str,
    ordered_candidates: Sequence[CandidateChunk],
    top_k: int,
) -> int:
    if not ordered_candidates:
        return 0
    min_rerank = 12 if top_k >= 5 else MIN_INTERACTIVE_RERANK_CANDIDATES
    max_rerank = 16 if top_k >= 5 else MAX_INTERACTIVE_RERANK_CANDIDATES
    if comparison_subqueries(question):
        return min(len(ordered_candidates), max(top_k * 2, max_rerank))
    return min(
        len(ordered_candidates),
        max(top_k + 1, min_rerank),
    )


def select_rerank_candidate_pool(
    *,
    ordered_candidates: Sequence[CandidateChunk],
    coverage_groups: Sequence[set[str]],
    limit: int,
) -> list[CandidateChunk]:
    if not ordered_candidates:
        return []

    selected = list(ordered_candidates[:limit])
    selected_ids = {candidate.chunk_id for candidate in selected}
    for hit_ids in coverage_groups:
        if any(candidate.chunk_id in hit_ids for candidate in selected):
            continue
        for candidate in ordered_candidates:
            if candidate.chunk_id not in hit_ids or candidate.chunk_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.chunk_id)
            break

    return selected


def select_final_chunks(
    *,
    ranked_candidates: Sequence[CandidateChunk],
    coverage_groups: Sequence[set[str]],
    top_k: int,
) -> list[CandidateChunk]:
    if not coverage_groups:
        return list(ranked_candidates[:top_k])

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
        if len(selected) >= top_k:
            break

    return selected[:top_k]


def should_rerank_candidates(
    *,
    question: str,
    ordered_candidates: Sequence[CandidateChunk],
    top_k: int,
) -> bool:
    if len(ordered_candidates) <= 1:
        return False
    if comparison_subqueries(question):
        return True

    top_window = list(ordered_candidates[: max(top_k, 4)])
    if len(top_window) <= 1:
        return False

    fused_margin = top_window[0].fused_score - top_window[-1].fused_score
    if fused_margin >= FUSED_SCORE_DOMINANCE_MARGIN:
        return False

    dominant_document_count = Counter(
        candidate.document_id for candidate in top_window
    ).most_common(1)[0][1]
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
