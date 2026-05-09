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
    return HealthResponse(
        status="ok",
        ollama_base_url=container.settings.ollama_base_url,
        embed_model=container.settings.embed_model,
        chat_model=container.settings.chat_model,
        collection_name="all_chunks",
        indexed_chunks=indexed_chunks,
        ingestionMode=container.ingestion_dispatcher.mode,
        ocrEnabled=container.ocr_service.enabled,
        ocrAvailable=container.ocr_service.is_available(),
    )
