from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import get_container, get_user_id
from app.models.schemas import GraphResponse, ReclusterResponse, TopicSummaryPayload
from app.services.container import ServiceContainer

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("", response_model=list[TopicSummaryPayload])
def list_topics(
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> list[TopicSummaryPayload]:
    return [
        TopicSummaryPayload(
            id=topic.id,
            label=topic.label,
            chunkCount=topic.chunk_count,
            documentCount=topic.document_count,
        )
        for topic in container.topic_index_service.list_topics(user_id=user_id)
    ]


@router.post("/recluster", response_model=ReclusterResponse)
def recluster_topics(
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> ReclusterResponse:
    result = container.topic_index_service.recluster_topics(user_id=user_id)
    return ReclusterResponse(
        topics=[
            TopicSummaryPayload(
                id=topic.id,
                label=topic.label,
                chunkCount=topic.chunk_count,
                documentCount=topic.document_count,
            )
            for topic in result.topics
        ],
        indexedChunks=result.indexed_chunks,
        documentCount=result.document_count,
    )


@router.get("/graph", response_model=GraphResponse)
def get_topic_graph(
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> GraphResponse:
    graph = container.topic_index_service.graph_data(user_id=user_id)
    return GraphResponse(
        nodes=graph["nodes"],
        edges=graph["edges"],
    )
