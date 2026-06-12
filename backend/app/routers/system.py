from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import get_container, get_user_id
from app.models.schemas import HealthResponse
from app.services.container import ServiceContainer

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> HealthResponse:
    indexed_chunks = container.document_service.count_indexed_chunks(user_id=user_id)
    chat_model = container.settings.chat_model.lower()
    thinking_supported = any(
        x in chat_model
        for x in ["deepseek-r1", "reason", "thinking", "o1-", "o3-", "nemotron"]
    )

    return HealthResponse(
        status="ok",
        nvidia_base_url=container.settings.nvidia_base_url,
        embed_model=container.settings.embed_model,
        embeddingDimensions=container.settings.embedding_dimensions,
        chat_model=container.settings.chat_model,
        collection_name="all_chunks",
        indexed_chunks=indexed_chunks,
        ingestionMode=container.ingestion_dispatcher.mode,
        parserAvailable=container.document_parser.is_available(),
        ocrEnabled=container.document_parser.ocr_enabled,
        ocrAvailable=container.document_parser.ocr_pipeline_available(),
        thinkingSupported=thinking_supported,
    )
