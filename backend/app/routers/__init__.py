from app.routers.analytics import router as analytics_router
from app.routers.chat import router as chat_router
from app.routers.documents import router as documents_router
from app.routers.events import router as events_router
from app.routers.kg import router as kg_router
from app.routers.sessions import router as sessions_router
from app.routers.system import router as system_router
from app.routers.topics import router as topics_router

__all__ = [
    "analytics_router",
    "chat_router",
    "documents_router",
    "events_router",
    "kg_router",
    "sessions_router",
    "system_router",
    "topics_router",
]
