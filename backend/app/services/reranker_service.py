from __future__ import annotations

import logging
import re
from threading import Lock
from typing import Any

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
LOGGER = logging.getLogger(__name__)


class RerankerService:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any | None = None
        self._model_error: Exception | None = None
        self._model_lock = Lock()

    def score_pairs(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []

        try:
            model = self._get_model()
        except Exception as error:  # noqa: BLE001
            if self._model_error is None:
                self._model_error = error
                LOGGER.warning(
                    "Cross-encoder reranker is unavailable; falling back to lexical overlap scoring.",
                    exc_info=True,
                )
            return self._fallback_scores(query, passages)

        pairs = [(query, passage) for passage in passages]
        try:
            scores = model.predict(
                pairs,
                batch_size=16,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        except Exception as error:  # noqa: BLE001
            LOGGER.warning(
                "Cross-encoder reranker prediction failed; falling back to lexical overlap scoring.",
                exc_info=True,
            )
            return self._fallback_scores(query, passages)
        return [float(score) for score in scores.tolist()]

    def _get_model(self):
        if self._model_error is not None:
            raise self._model_error

        model = self._model
        if model is not None:
            return model

        with self._model_lock:
            if self._model_error is not None:
                raise self._model_error
            model = self._model
            if model is None:
                try:
                    from sentence_transformers import CrossEncoder

                    model = CrossEncoder(
                        self._model_name,
                        device="cpu",
                        max_length=512,
                    )
                except Exception as error:  # noqa: BLE001
                    self._model_error = error
                    raise
                self._model = model
        return model

    def _fallback_scores(self, query: str, passages: list[str]) -> list[float]:
        query_tokens = set(TOKEN_PATTERN.findall(query.lower()))
        if not query_tokens:
            return [0.0 for _ in passages]

        scores: list[float] = []
        for passage in passages:
            passage_tokens = set(TOKEN_PATTERN.findall(passage.lower()))
            if not passage_tokens:
                scores.append(0.0)
                continue

            overlap = query_tokens & passage_tokens
            overlap_score = len(overlap) / len(query_tokens)
            density_score = len(overlap) / len(passage_tokens)
            scores.append((overlap_score * 0.75) + (density_score * 0.25))
        return scores
