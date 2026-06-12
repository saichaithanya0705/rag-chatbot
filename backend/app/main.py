from __future__ import annotations

from contextlib import asynccontextmanager, suppress
import asyncio
import logging

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

settings = load_settings()
logger = logging.getLogger(__name__)


def _bootstrap_container_sync():
    from app.services.container import build_container

    container = build_container(settings)
    container.document_service.sync_active_chunk_metadata()
    container.ingestion_dispatcher.start(container=container)
    return container


async def _bootstrap_container(app: FastAPI) -> None:
    try:
        app.state.container = await asyncio.to_thread(_bootstrap_container_sync)
    except Exception as error:  # noqa: BLE001
        app.state.container_startup_error = error
        logger.exception("Backend container bootstrap failed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_runtime_directories(settings)
    app.state.container = None
    app.state.container_startup_error = None
    bootstrap_task = asyncio.create_task(_bootstrap_container(app))
    app.state.container_bootstrap_task = bootstrap_task
    try:
        yield
    finally:
        if not bootstrap_task.done():
            bootstrap_task.cancel()
            with suppress(asyncio.CancelledError):
                await bootstrap_task
        else:
            with suppress(Exception):
                await bootstrap_task

        container = app.state.container
        if container is not None:
            await container.ingestion_dispatcher.aclose()
            await container.aclose()


app = FastAPI(title=settings.project_name, lifespan=lifespan)
app.state.settings = settings
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
