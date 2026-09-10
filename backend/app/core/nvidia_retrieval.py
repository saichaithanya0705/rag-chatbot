from __future__ import annotations

NVIDIA_HOSTED_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_RERANKER_MODEL = "nvidia/llama-nemotron-rerank-vl-1b-v2"
DEFAULT_HOSTED_RERANK_URL = (
    "https://ai.api.nvidia.com/v1/retrieval/nvidia/"
    "llama-nemotron-rerank-vl-1b-v2/reranking"
)


def resolve_ranking_url(*, base_url: str, model_name: str) -> str:
    normalized_base = base_url.rstrip("/")
    if normalized_base == NVIDIA_HOSTED_BASE_URL:
        if model_name != DEFAULT_RERANKER_MODEL:
            raise ValueError(
                "The hosted NVIDIA reranker endpoint is only configured for "
                f"{DEFAULT_RERANKER_MODEL!r}; received {model_name!r}. "
                "Set RAG_NVIDIA_BASE_URL to a compatible self-hosted NIM endpoint "
                "when using another model."
            )
        return DEFAULT_HOSTED_RERANK_URL
    return f"{normalized_base}/ranking"
