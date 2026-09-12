from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from typing import Protocol, Sequence

from app.services.rag.rag_answer_text import (
    extract_direct_qa_pair,
    first_sentence,
    is_informative_answer_sentence,
)
from app.services.rag.rag_grounding import clean_context_snippet, normalize_context_text
from app.services.rag.rag_types import RetrievedContext


MAX_FALLBACK_CONTEXTS = 5
MAX_CANDIDATES = 24
MAX_CANDIDATE_CHARS = 480
MIN_SEMANTIC_SCORE = 0.34
DEFAULT_INFERENCE_TIMEOUT_SECONDS = 8.0
SYNTHESIS_REQUEST_PATTERN = re.compile(
    r"\b(?:analy[sz]e|compare|contrast|discuss|explain|how|summari[sz]e|synthesi[sz]e|why)\b",
    re.IGNORECASE,
)


class LocalTextEmbedder(Protocol):
    async def embed_texts_locally(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class ExtractiveFallbackResult:
    answer: str
    context: RetrievedContext
    score: float


@dataclass(frozen=True)
class _Candidate:
    text: str
    context: RetrievedContext


class ExtractiveFallbackService:
    """Select a cited answer sentence with the local sentence-embedding model."""

    def __init__(
        self,
        embedder: LocalTextEmbedder,
        *,
        enabled: bool = True,
        minimum_score: float = MIN_SEMANTIC_SCORE,
        timeout_seconds: float = DEFAULT_INFERENCE_TIMEOUT_SECONDS,
    ) -> None:
        if not 0.0 <= minimum_score <= 1.0:
            raise ValueError("minimum_score must be between 0 and 1.")
        if timeout_seconds <= 0.0:
            raise ValueError("timeout_seconds must be greater than zero.")
        self._embedder = embedder
        self._enabled = enabled
        self._minimum_score = minimum_score
        self._timeout_seconds = timeout_seconds

    async def answer(
        self,
        question: str,
        contexts: Sequence[RetrievedContext],
    ) -> ExtractiveFallbackResult | None:
        normalized_question = " ".join(question.split())
        if (
            not self._enabled
            or not normalized_question
            or not contexts
            or SYNTHESIS_REQUEST_PATTERN.search(normalized_question)
        ):
            return None

        candidates = _answer_candidates(contexts)
        if not candidates:
            return None

        embeddings = await asyncio.wait_for(
            self._embedder.embed_texts_locally(
                [normalized_question, *(candidate.text for candidate in candidates)]
            ),
            timeout=self._timeout_seconds,
        )
        _validate_embeddings(embeddings, expected_count=len(candidates) + 1)

        question_embedding = embeddings[0]
        scored_candidates = [
            (_cosine_similarity(question_embedding, embedding), candidate)
            for candidate, embedding in zip(candidates, embeddings[1:], strict=True)
        ]
        score, candidate = max(scored_candidates, key=lambda item: item[0])
        if score < self._minimum_score:
            return None
        return ExtractiveFallbackResult(
            answer=candidate.text,
            context=candidate.context,
            score=score,
        )


def _answer_candidates(contexts: Sequence[RetrievedContext]) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    seen: set[tuple[str, str]] = set()

    for context in contexts[:MAX_FALLBACK_CONTEXTS]:
        qa_pair = extract_direct_qa_pair(context.text)
        if qa_pair is not None:
            _append_candidate(candidates, seen, context=context, text=qa_pair[1])

        normalized = normalize_context_text(context.text)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", normalized):
            _append_candidate(candidates, seen, context=context, text=sentence)
            if len(candidates) >= MAX_CANDIDATES:
                return candidates

    return candidates


def _append_candidate(
    candidates: list[_Candidate],
    seen: set[tuple[str, str]],
    *,
    context: RetrievedContext,
    text: str,
) -> None:
    candidate = first_sentence(clean_context_snippet(text, max_chars=MAX_CANDIDATE_CHARS))
    key = (context.id, candidate.casefold())
    if not is_informative_answer_sentence(candidate) or key in seen:
        return
    seen.add(key)
    candidates.append(_Candidate(text=candidate, context=context))


def _validate_embeddings(embeddings: list[list[float]], *, expected_count: int) -> None:
    if len(embeddings) != expected_count:
        raise ValueError(
            f"Local extractive fallback returned {len(embeddings)} embeddings; expected {expected_count}."
        )
    dimensions = len(embeddings[0]) if embeddings else 0
    if dimensions == 0:
        raise ValueError("Local extractive fallback returned an empty embedding vector.")
    for index, embedding in enumerate(embeddings):
        if len(embedding) != dimensions:
            raise ValueError(
                f"Local extractive fallback embedding {index} has {len(embedding)} dimensions; "
                f"expected {dimensions}."
            )
        if not all(
            isinstance(value, (int, float)) and math.isfinite(float(value))
            for value in embedding
        ):
            raise ValueError(f"Local extractive fallback embedding {index} contains a non-finite value.")


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
