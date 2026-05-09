from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.celery_app import celery_app
from app.core.config import ensure_runtime_directories, load_settings
from app.services.container import build_container


@celery_app.task(name="rag_chat.ingest_pdf")
def ingest_pdf_task(pdf_path: str, document_id: str, pdf_name: str, user_id: str) -> dict[str, object]:
    settings = load_settings()
    ensure_runtime_directories(settings)
    container = build_container(settings)
    try:
        result = asyncio.run(
            container.ingestion_service.ingest_pdf(
                Path(pdf_path),
                document_id=document_id,
                pdf_name=pdf_name,
                user_id=user_id,
            )
        )
        asyncio.run(
            container.ingestion_service.postprocess_document(
                document_id=document_id,
                user_id=user_id,
            )
        )
        container.topic_index_service.recluster_topics(user_id=user_id)
        container.document_service.mark_user_documents_indexed(user_id=user_id)
    finally:
        asyncio.run(container.aclose())
    return {
        "document_id": result.document_id,
        "pdf_name": result.pdf_name,
        "page_count": result.page_count,
        "chunk_count": result.chunk_count,
    }


@celery_app.task(name="rag_chat.recluster_topics")
def recluster_topics_task(user_id: str) -> dict[str, object]:
    settings = load_settings()
    ensure_runtime_directories(settings)
    container = build_container(settings)
    try:
        result = container.topic_index_service.recluster_topics(user_id=user_id)
        container.document_service.mark_user_documents_indexed(user_id=user_id)
    finally:
        asyncio.run(container.aclose())
    return {
        "user_id": user_id,
        "indexed_chunks": result.indexed_chunks,
        "document_count": result.document_count,
    }
