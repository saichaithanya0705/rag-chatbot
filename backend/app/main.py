from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import ensure_runtime_directories, load_settings
from app.routers import (
    analytics_router,
    chat_router,
    documents_router,
    events_router,
    kg_router,
    sessions_router,
    system_router,
    topics_router,
)
from app.services.container import build_container

settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_runtime_directories(settings)
    container = build_container(settings)
    app.state.container = container
    container.document_service.sync_active_chunk_metadata()
    container.ingestion_dispatcher.start(container=container)
    try:
        yield
    finally:
        await container.ingestion_dispatcher.aclose()
        await container.aclose()


app = FastAPI(title=settings.project_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=settings.allowed_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system_router, prefix=settings.api_prefix)
app.include_router(documents_router, prefix=settings.api_prefix)
app.include_router(events_router, prefix=settings.api_prefix)
app.include_router(kg_router, prefix=settings.api_prefix)
app.include_router(topics_router, prefix=settings.api_prefix)
app.include_router(analytics_router, prefix=settings.api_prefix)
app.include_router(sessions_router, prefix=settings.api_prefix)
app.include_router(chat_router, prefix=settings.api_prefix)
