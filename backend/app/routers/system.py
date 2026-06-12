from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.models.schemas import HealthResponse

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

router = APIRouter(prefix="/system", tags=["system"])


def _thinking_supported(chat_model: str) -> bool:
    normalized = chat_model.lower()
    return any(
        marker in normalized
        for marker in ("deepseek-r1", "reason", "thinking", "o1-", "o3-", "nemotron")
    )


def _build_health_response(
    *,
    settings: Settings,
    status_value: str,
    indexed_chunks: int,
    ingestion_mode: str,
    parser_available: bool,
    ocr_available: bool,
) -> HealthResponse:
    return HealthResponse(
        status=status_value,
        nvidiaBaseUrl=settings.nvidia_base_url,
        embed_model=settings.embed_model,
        embeddingDimensions=settings.embedding_dimensions,
        chat_model=settings.chat_model,
        collection_name="all_chunks",
        indexed_chunks=indexed_chunks,
        ingestionMode=ingestion_mode,
        parserAvailable=parser_available,
        ocrEnabled=settings.docling_ocr_enabled,
        ocrAvailable=ocr_available,
        thinkingSupported=_thinking_supported(settings.chat_model),
    )


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    startup_error = getattr(request.app.state, "container_startup_error", None)
    if startup_error is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The service failed during startup. Check backend logs for details.",
        )

    container = getattr(request.app.state, "container", None)
    if container is None:
        settings = getattr(request.app.state, "settings", get_settings())
        return _build_health_response(
            settings=settings,
            status_value="starting",
            indexed_chunks=0,
            ingestion_mode="starting",
            parser_available=False,
            ocr_available=False,
        )

    return _build_health_response(
        settings=container.settings,
        status_value="ok",
        indexed_chunks=container.document_service.count_indexed_chunks_all(),
        ingestion_mode=container.ingestion_dispatcher.mode,
        parser_available=container.document_parser.is_available(),
        ocr_available=container.document_parser.ocr_pipeline_available(),
    )
