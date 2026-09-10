from __future__ import annotations

import json
import logging
import math
import re
import httpx

from app.core.nvidia_retrieval import (
    NVIDIA_HOSTED_BASE_URL,
    resolve_ranking_url,
)

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
LOGGER = logging.getLogger(__name__)


class RerankerResponseError(ValueError):
    """The reranking provider returned data outside its documented contract."""


def parse_ranking_scores(payload: object, *, passage_count: int) -> list[float]:
    if not isinstance(payload, dict) or not isinstance(payload.get("rankings"), list):
        raise RerankerResponseError("Reranking response must contain a rankings list.")

    scores = [0.0] * passage_count
    seen: set[int] = set()
    for item in payload["rankings"]:
        if not isinstance(item, dict):
            raise RerankerResponseError("Each reranking result must be an object.")
        index = item.get("index")
        logit = item.get("logit")
        if type(index) is not int or not 0 <= index < passage_count or index in seen:
            raise RerankerResponseError("Reranking indexes must be unique and in range.")
        if isinstance(logit, bool) or not isinstance(logit, (int, float)):
            raise RerankerResponseError("Reranking logits must be numeric.")
        numeric_logit = float(logit)
        if not math.isfinite(numeric_logit):
            raise RerankerResponseError("Reranking logits must be finite.")
        seen.add(index)
        scores[index] = numeric_logit

    if len(seen) != passage_count:
        raise RerankerResponseError("Reranking response is incomplete.")
    return scores


class RerankerService:
    def __init__(
        self,
        model_name: str,
        *,
        nvidia_base_url: str = NVIDIA_HOSTED_BASE_URL,
        nvidia_api_key: str = "",
    ) -> None:
        self._model_name = model_name
        self._nvidia_base_url = nvidia_base_url.rstrip("/")
        self._nvidia_api_key = nvidia_api_key
        self._ranking_url = resolve_ranking_url(
            base_url=self._nvidia_base_url,
            model_name=model_name,
        )

    def score_pairs(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []

        # If API key is missing, immediately use the local lexical fallback
        if not self._nvidia_api_key:
            LOGGER.warning("NVIDIA API key not set; falling back to lexical overlap scoring.")
            return self._fallback_scores(query, passages)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._nvidia_api_key}",
        }
        payload = {
            "model": self._model_name,
            "query": {"text": query},
            "passages": [{"text": p} for p in passages],
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self._ranking_url,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                res_data = response.json()
                
            return parse_ranking_scores(res_data, passage_count=len(passages))
        except (httpx.HTTPError, json.JSONDecodeError, RerankerResponseError):
            LOGGER.warning(
                "NVIDIA NIM reranker failed; falling back to lexical overlap scoring.",
                exc_info=True,
            )
            return self._fallback_scores(query, passages)

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

