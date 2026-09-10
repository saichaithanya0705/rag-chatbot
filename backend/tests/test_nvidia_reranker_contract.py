from __future__ import annotations

import math

import pytest

from app.core.nvidia_retrieval import (
    DEFAULT_HOSTED_RERANK_URL,
    DEFAULT_RERANKER_MODEL,
    NVIDIA_HOSTED_BASE_URL,
    resolve_ranking_url,
)
from app.services.reranker_service import RerankerResponseError, parse_ranking_scores


def test_hosted_endpoint_is_model_specific() -> None:
    assert resolve_ranking_url(
        base_url=NVIDIA_HOSTED_BASE_URL,
        model_name=DEFAULT_RERANKER_MODEL,
    ) == DEFAULT_HOSTED_RERANK_URL


def test_unknown_hosted_model_fails_before_network_access() -> None:
    with pytest.raises(ValueError, match="self-hosted"):
        resolve_ranking_url(
            base_url=NVIDIA_HOSTED_BASE_URL,
            model_name="nvidia/unknown-reranker",
        )


def test_self_hosted_nim_keeps_standard_ranking_route() -> None:
    assert resolve_ranking_url(
        base_url="http://reranker.internal:8000/v1/",
        model_name="custom/reranker",
    ) == "http://reranker.internal:8000/v1/ranking"


def test_ranking_scores_restore_passage_order() -> None:
    assert parse_ranking_scores(
        {"rankings": [{"index": 1, "logit": 8.5}, {"index": 0, "logit": -2.0}]},
        passage_count=2,
    ) == [-2.0, 8.5]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"rankings": [{"index": 0, "logit": 1.0}]},
        {"rankings": [{"index": 0, "logit": 1.0}, {"index": 0, "logit": 2.0}]},
        {"rankings": [{"index": True, "logit": 1.0}, {"index": 1, "logit": 2.0}]},
        {"rankings": [{"index": 0, "logit": math.inf}, {"index": 1, "logit": 2.0}]},
    ],
)
def test_invalid_ranking_contract_is_rejected(payload: object) -> None:
    with pytest.raises(RerankerResponseError):
        parse_ranking_scores(payload, passage_count=2)
