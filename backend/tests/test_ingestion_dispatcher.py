from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from app.core.config import load_settings
from app.services.ingestion_dispatcher import IngestionDispatcher


def _test_settings(tmp_path: Path):
    base_settings = load_settings()
    data_dir = tmp_path / "data"
    celery_root = data_dir / "celery"
    return replace(
        base_settings,
        data_dir=data_dir,
        uploads_dir=data_dir / "uploads",
        sqlite_path=data_dir / "app.db",
        chroma_path=data_dir / "chroma",
        kg_path=data_dir / "kg.pkl",
        celery_root=celery_root,
        celery_queue_dir=celery_root / "queue",
        celery_reply_dir=celery_root / "reply",
        celery_control_dir=celery_root / "control",
        celery_processed_dir=celery_root / "processed",
        docling_artifacts_dir=data_dir / "docling-models",
        celery_broker_url="filesystem://",
        celery_transport_role="producer",
        celery_task_always_eager=False,
    )


def test_start_does_not_build_worker_container_without_jobs(tmp_path, monkeypatch):
    settings = _test_settings(tmp_path)
    dispatcher = IngestionDispatcher(settings=settings)
    fake_container = SimpleNamespace(
        document_service=SimpleNamespace(list_active_documents=lambda: []),
    )

    def fail_build_container(_settings):
        raise AssertionError("worker container should not build during startup without queued jobs")

    monkeypatch.setattr("app.services.container.build_container", fail_build_container)

    assert dispatcher.start(container=fake_container) is True
    asyncio.run(dispatcher.aclose())
