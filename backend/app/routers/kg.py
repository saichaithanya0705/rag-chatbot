from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from app.dependencies import get_container, get_user_id
from app.models.schemas import GraphResponse

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

router = APIRouter(prefix="/kg", tags=["kg"])


@router.get("/graph", response_model=GraphResponse)
def get_knowledge_graph(
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> GraphResponse:
    graph = container.topic_index_service.graph_data(user_id=user_id)
    return GraphResponse(
        nodes=graph["nodes"],
        edges=graph["edges"],
    )
