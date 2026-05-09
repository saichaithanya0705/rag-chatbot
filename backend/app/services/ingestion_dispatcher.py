from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
import queue
import threading
from typing import TYPE_CHECKING

from app.core.config import Settings

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionJob:
    document_id: str
    pdf_path: Path
    pdf_name: str
    user_id: str


@dataclass(frozen=True)
class TopicReclusterJob:
    user_id: str
    attempt: int = 0


@dataclass(frozen=True)
class DocumentPostprocessJob:
    document_id: str
    user_id: str
    attempt: int = 0


QueueJob = IngestionJob | TopicReclusterJob | DocumentPostprocessJob | None


class IngestionDispatcher:
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings
        self._queue: queue.Queue[QueueJob] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._thread_ready = threading.Event()
        self._state_lock = threading.Lock()
        self._startup_error: Exception | None = None
        self._pending_ingestion_ids: set[str] = set()
        self._pending_recluster_user_ids: set[str] = set()
        self._pending_postprocess_ids: set[str] = set()

    @property
    def mode(self) -> str:
        if (
            self._settings.celery_broker_url.startswith("filesystem://")
            and self._settings.celery_transport_role != "consumer"
            and not self._settings.celery_task_always_eager
        ):
            return "local"
        return "celery"

    def start(self, *, container: ServiceContainer) -> bool:
        if self.mode != "local":
            return False

        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._queue = queue.Queue()
            self._thread_ready = threading.Event()
            self._startup_error = None
            self._pending_ingestion_ids.clear()
            self._pending_recluster_user_ids.clear()
            self._pending_postprocess_ids.clear()
            self._thread = threading.Thread(
                target=self._worker_main,
                name="local-ingestion-runner",
                daemon=True,
            )
            self._thread.start()

        if not self._thread_ready.wait(timeout=20.0):
            raise RuntimeError("Local ingestion runner did not become ready in time.")
        if self._startup_error is not None:
            raise RuntimeError("Local ingestion runner failed during startup.") from self._startup_error

        self._resume_active_documents(container=container)
        return True

    async def aclose(self) -> None:
        thread = self._thread
        if thread is None:
            return

        self._queue.put(None)
        await asyncio.to_thread(thread.join, 5.0)
        with self._state_lock:
            self._thread = None
            self._pending_ingestion_ids.clear()
            self._pending_recluster_user_ids.clear()
            self._pending_postprocess_ids.clear()

    def enqueue_ingestion(self, *, document_id: str, pdf_path: Path, pdf_name: str, user_id: str) -> None:
        if self.mode == "local":
            self._enqueue_local_ingestion(
                document_id=document_id,
                pdf_path=pdf_path,
                pdf_name=pdf_name,
                user_id=user_id,
            )
            return

        from app.tasks.ingestion_tasks import ingest_pdf_task

        ingest_pdf_task.apply_async(
            args=[str(pdf_path), document_id, pdf_name, user_id],
            queue=self._settings.celery_queue_name,
        )

    def enqueue_topic_recluster(self, *, user_id: str) -> None:
        if self.mode == "local":
            self._enqueue_local_recluster(user_id=user_id)
            return

        from app.tasks.ingestion_tasks import recluster_topics_task

        recluster_topics_task.apply_async(
            args=[user_id],
            queue=self._settings.celery_queue_name,
        )

    def _resume_active_documents(self, *, container: ServiceContainer) -> None:
        active_documents = container.document_service.list_active_documents()
        for document in active_documents:
            document_id = str(document["id"])
            user_id = str(document["user_id"])
            status = str(document["status"])
            if (
                status == "finalizing"
                and container.document_service.has_published_chunks(document_id, user_id=user_id)
            ):
                self._enqueue_local_recluster(user_id=user_id)
                continue
            if (
                status == "clustering"
                and container.document_service.has_published_chunks(document_id, user_id=user_id)
            ):
                self._enqueue_local_postprocess(document_id=document_id, user_id=user_id)
                continue
            self._enqueue_local_ingestion(
                document_id=document_id,
                pdf_path=Path(str(document["source_path"])),
                pdf_name=str(document["pdf_name"]),
                user_id=user_id,
            )

    def _enqueue_local_ingestion(
        self,
        *,
        document_id: str,
        pdf_path: Path,
        pdf_name: str,
        user_id: str,
    ) -> None:
        with self._state_lock:
            if self._thread is None or not self._thread.is_alive():
                raise RuntimeError("Local ingestion runner is not running.")
            if document_id in self._pending_ingestion_ids:
                return
            self._pending_ingestion_ids.add(document_id)
        self._queue.put(
            IngestionJob(
                document_id=document_id,
                pdf_path=pdf_path,
                pdf_name=pdf_name,
                user_id=user_id,
            )
        )

    def _enqueue_local_recluster(self, *, user_id: str, attempt: int = 0) -> None:
        with self._state_lock:
            if self._thread is None or not self._thread.is_alive():
                raise RuntimeError("Local ingestion runner is not running.")
            if user_id in self._pending_recluster_user_ids:
                return
            self._pending_recluster_user_ids.add(user_id)
        self._queue.put(TopicReclusterJob(user_id=user_id, attempt=attempt))

    def _enqueue_local_postprocess(
        self,
        *,
        document_id: str,
        user_id: str,
        attempt: int = 0,
    ) -> None:
        with self._state_lock:
            if self._thread is None or not self._thread.is_alive():
                raise RuntimeError("Local ingestion runner is not running.")
            if document_id in self._pending_postprocess_ids:
                return
            self._pending_postprocess_ids.add(document_id)
        self._queue.put(
            DocumentPostprocessJob(
                document_id=document_id,
                user_id=user_id,
                attempt=attempt,
            )
        )

    def _worker_main(self) -> None:
        loop: asyncio.AbstractEventLoop | None = None
        try:
            from app.services.container import build_container

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            container = build_container(self._settings)
        except Exception as error:
            self._startup_error = error
            self._thread_ready.set()
            logger.exception("Local ingestion runner failed to start.")
            return

        self._thread_ready.set()
        try:
            while True:
                job = self._queue.get()
                if job is None:
                    self._queue.task_done()
                    break
                try:
                    if isinstance(job, IngestionJob):
                        loop.run_until_complete(
                            container.ingestion_service.ingest_pdf(
                                job.pdf_path,
                                document_id=job.document_id,
                                pdf_name=job.pdf_name,
                                user_id=job.user_id,
                            )
                        )
                        self._enqueue_local_postprocess(
                            document_id=job.document_id,
                            user_id=job.user_id,
                        )
                    elif isinstance(job, TopicReclusterJob):
                        container.topic_index_service.recluster_topics(user_id=job.user_id)
                        container.document_service.mark_user_documents_indexed(
                            user_id=job.user_id,
                        )
                    else:
                        loop.run_until_complete(
                            container.ingestion_service.postprocess_document(
                                document_id=job.document_id,
                                user_id=job.user_id,
                            )
                        )
                        self._enqueue_local_recluster(user_id=job.user_id)
                except Exception:
                    if isinstance(job, IngestionJob):
                        logger.exception(
                            "Failed to ingest document %s for user %s.",
                            job.document_id,
                            job.user_id,
                        )
                    elif isinstance(job, TopicReclusterJob):
                        logger.exception(
                            "Failed to recluster topics for user %s (attempt %s).",
                            job.user_id,
                            job.attempt + 1,
                        )
                        with self._state_lock:
                            self._pending_recluster_user_ids.discard(job.user_id)
                        if job.attempt < 2:
                            self._enqueue_local_recluster(
                                user_id=job.user_id,
                                attempt=job.attempt + 1,
                            )
                    else:
                        logger.exception(
                            "Failed to post-process document %s for user %s (attempt %s).",
                            job.document_id,
                            job.user_id,
                            job.attempt + 1,
                        )
                        with self._state_lock:
                            self._pending_postprocess_ids.discard(job.document_id)
                        if job.attempt < 2:
                            self._enqueue_local_postprocess(
                                document_id=job.document_id,
                                user_id=job.user_id,
                                attempt=job.attempt + 1,
                            )
                finally:
                    with self._state_lock:
                        if isinstance(job, IngestionJob):
                            self._pending_ingestion_ids.discard(job.document_id)
                        elif isinstance(job, TopicReclusterJob):
                            self._pending_recluster_user_ids.discard(job.user_id)
                        else:
                            self._pending_postprocess_ids.discard(job.document_id)
                    self._queue.task_done()
        finally:
            try:
                if loop is not None:
                    loop.run_until_complete(container.aclose())
            except Exception:
                logger.exception("Failed to close local ingestion runner services cleanly.")
            finally:
                asyncio.set_event_loop(None)
                if loop is not None:
                    loop.close()
