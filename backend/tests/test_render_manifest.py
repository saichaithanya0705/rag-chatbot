from __future__ import annotations

from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_RENDER_EMBED_MODEL = "nvidia/nemotron-3-embed-1b"
ACTIVE_RENDER_EMBED_DIMENSIONS = "2048"
RETIRED_RENDER_EMBED_MODELS = {"nvidia/llama-nemotron-embed-1b-v2"}


def _render_service() -> dict[str, object]:
    manifest = yaml.safe_load((REPOSITORY_ROOT / "render.yaml").read_text(encoding="utf-8"))
    services = manifest.get("services", [])
    assert len(services) == 1
    return services[0]


def test_render_embedding_contract_uses_supported_model_and_dimensions() -> None:
    service = _render_service()
    env = {item["key"]: item.get("value") for item in service["envVars"]}

    assert env["RAG_EMBED_MODEL"] == ACTIVE_RENDER_EMBED_MODEL
    assert env["RAG_EMBED_MODEL"] not in RETIRED_RENDER_EMBED_MODELS
    assert env["RAG_EMBEDDING_DIMENSIONS"] == ACTIVE_RENDER_EMBED_DIMENSIONS


def test_render_manifest_declares_durable_ingestion_storage() -> None:
    service = _render_service()

    assert service["plan"] != "free"
    assert service["disk"]["mountPath"] == "/app/data"
    assert service["healthCheckPath"] == "/api/system/ready"
