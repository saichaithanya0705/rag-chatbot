from __future__ import annotations

import logging
import re
from typing import Any
import httpx

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
LOGGER = logging.getLogger(__name__)


class RerankerService:
    def __init__(
        self,
        model_name: str,
        *,
        nvidia_base_url: str = "https://integrate.api.nvidia.com/v1",
        nvidia_api_key: str = "",
    ) -> None:
        self._model_name = model_name
        self._nvidia_base_url = nvidia_base_url.rstrip("/")
        self._nvidia_api_key = nvidia_api_key

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
                    f"{self._nvidia_base_url}/ranking",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                res_data = response.json()
                
            rankings = res_data.get("rankings", [])
            scores = [0.0] * len(passages)
            for item in rankings:
                idx = item.get("index")
                logit = item.get("logit", 0.0)
                if idx is not None and 0 <= idx < len(scores):
                    scores[idx] = float(logit)
            return scores
        except Exception as error:  # noqa: BLE001
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

