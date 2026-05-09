from __future__ import annotations

import os

from celery import Celery

from app.core.config import ensure_runtime_directories, load_settings

settings = load_settings()
ensure_runtime_directories(settings)


def _broker_transport_options() -> dict[str, object]:
    if not settings.celery_broker_url.startswith("filesystem://"):
        return {}

    producer_role = settings.celery_transport_role != "consumer"
    data_folder_in = settings.celery_queue_dir if producer_role else settings.celery_reply_dir
    data_folder_out = settings.celery_reply_dir if producer_role else settings.celery_queue_dir
    return {
        "data_folder_in": str(data_folder_in),
        "data_folder_out": str(data_folder_out),
        "control_folder": str(settings.celery_control_dir),
        "processed_folder": str(settings.celery_processed_dir),
        "store_processed": False,
    }


celery_app = Celery(
    "rag_chat",
    broker=settings.celery_broker_url,
    include=["app.tasks.ingestion_tasks"],
)

celery_app.conf.update(
    task_default_queue=settings.celery_queue_name,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_store_errors_even_if_ignored=True,
    task_always_eager=settings.celery_task_always_eager,
    broker_connection_retry_on_startup=True,
    broker_transport_options=_broker_transport_options(),
)

if os.name == "nt":
    celery_app.conf.worker_pool = "solo"
