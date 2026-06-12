from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from app.dependencies import get_container, get_user_id
from app.models.schemas import AnalyticsSummaryResponse, AnalyticsTopicPayload

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(file_path.stat().st_size for file_path in path.rglob("*") if file_path.is_file())


@router.get("/summary", response_model=AnalyticsSummaryResponse)
def get_analytics_summary(
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> AnalyticsSummaryResponse:
    documents = [
        document
        for document in container.document_service.list_documents(user_id=user_id)
        if str(document["status"]) == "indexed"
    ]
    topics = container.topic_index_service.list_topics(user_id=user_id)
    total_documents = len(documents)
    total_chunks = sum(int(document["chunk_count"]) for document in documents)
    avg_chunks_per_doc = round(total_chunks / total_documents, 1) if total_documents else 0.0
    storage_used_bytes = sum(_path_size(Path(str(document["source_path"]))) for document in documents)

    return AnalyticsSummaryResponse(
        totalDocuments=total_documents,
        totalChunks=total_chunks,
        totalTopics=len(topics),
        avgChunksPerDoc=avg_chunks_per_doc,
        topTopics=[
            AnalyticsTopicPayload(label=topic.label, chunkCount=topic.chunk_count)
            for topic in sorted(topics, key=lambda item: item.chunk_count, reverse=True)[:5]
        ],
        storageUsedBytes=storage_used_bytes,
    )
