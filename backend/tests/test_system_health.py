from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.routers.system import router


def _build_app(*, container=None, startup_error=None, settings=None) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.container = container
    app.state.container_startup_error = startup_error
    app.state.settings = settings or get_settings()
    return app


def test_health_reports_starting_without_container() -> None:
    app = _build_app()

    with TestClient(app) as client:
        response = client.get("/api/system/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "starting"
    assert payload["indexed_chunks"] == 0
    assert payload["ingestionMode"] == "starting"
    assert payload["parserAvailable"] is False
    assert payload["ocrAvailable"] is False


def test_health_reports_global_parser_capabilities_when_container_is_ready() -> None:
    settings = replace(get_settings(), chat_model="deepseek-r1")
    container = SimpleNamespace(
        settings=settings,
        document_service=SimpleNamespace(count_indexed_chunks_all=lambda: 7),
        ingestion_dispatcher=SimpleNamespace(mode="local"),
        document_parser=SimpleNamespace(
            is_available=lambda: True,
            ocr_pipeline_available=lambda: False,
        ),
    )
    app = _build_app(container=container, settings=settings)

    with TestClient(app) as client:
        response = client.get("/api/system/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["indexed_chunks"] == 7
    assert payload["parserAvailable"] is True
    assert payload["ocrAvailable"] is False
    assert payload["thinkingSupported"] is True


def test_health_returns_503_after_container_startup_failure() -> None:
    app = _build_app(startup_error=RuntimeError("boom"))

    with TestClient(app) as client:
        response = client.get("/api/system/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "The service failed during startup. Check backend logs for details."
