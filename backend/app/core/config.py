from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_name: str
    api_prefix: str
    backend_root: Path
    data_dir: Path
    uploads_dir: Path
    sqlite_path: Path
    chroma_path: Path
    kg_path: Path
    celery_root: Path
    celery_queue_dir: Path
    celery_reply_dir: Path
    celery_control_dir: Path
    celery_processed_dir: Path
    ollama_base_url: str
    embed_model: str
    chat_model: str
    reranker_model: str
    chat_history_collection_name: str
    cross_session_memory_enabled: bool
    celery_broker_url: str
    celery_queue_name: str
    celery_transport_role: str
    celery_task_always_eager: bool
    docling_artifacts_dir: Path
    docling_ocr_enabled: bool
    docling_table_structure_enabled: bool
    web_search_backend: str
    web_search_region: str
    web_search_max_results: int
    web_search_score_threshold: float
    allowed_origins: list[str]
    allowed_origin_regex: str
    topic_collection_prefix: str
    chunk_size: int
    chunk_overlap: int
    top_k: int


def _resolve_allowed_origins(raw_value: str | None) -> list[str]:
    if not raw_value:
        return [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ]
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _resolve_allowed_origin_regex(raw_value: str | None) -> str:
    candidate = raw_value.strip() if raw_value else r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    # Normalize common over-escaped env/file values so local dev ports keep matching.
    return candidate.replace("\\\\.", r"\.").replace("\\\\d", r"\d")


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    backend_root = Path(__file__).resolve().parents[2]
    data_dir = backend_root / "data"
    uploads_dir = data_dir / "uploads"
    sqlite_path = data_dir / "app.db"
    chroma_path = data_dir / "chroma"
    kg_path = data_dir / "kg.pkl"
    celery_root = data_dir / "celery"
    celery_queue_dir = celery_root / "queue"
    celery_reply_dir = celery_root / "reply"
    celery_control_dir = celery_root / "control"
    celery_processed_dir = celery_root / "processed"
    raw_docling_artifacts_dir = os.getenv("RAG_DOCLING_ARTIFACTS_DIR")
    docling_artifacts_dir = (
        Path(raw_docling_artifacts_dir).expanduser()
        if raw_docling_artifacts_dir
        else data_dir / "docling-models"
    )

    return Settings(
        project_name="Local RAG Chat Backend",
        api_prefix="/api",
        backend_root=backend_root,
        data_dir=data_dir,
        uploads_dir=uploads_dir,
        sqlite_path=sqlite_path,
        chroma_path=chroma_path,
        kg_path=kg_path,
        celery_root=celery_root,
        celery_queue_dir=celery_queue_dir,
        celery_reply_dir=celery_reply_dir,
        celery_control_dir=celery_control_dir,
        celery_processed_dir=celery_processed_dir,
        ollama_base_url=os.getenv("RAG_OLLAMA_BASE_URL", "http://localhost:11434"),
        embed_model=os.getenv("RAG_OLLAMA_EMBED_MODEL", "andersc/qwen3-embedding:0.6b"),
        chat_model=os.getenv("RAG_OLLAMA_CHAT_MODEL", "gemma4:31b-cloud"),
        reranker_model=os.getenv(
            "RAG_RERANKER_MODEL",
            "cross-encoder/ms-marco-MiniLM-L6-v2",
        ),
        chat_history_collection_name=os.getenv(
            "RAG_CHAT_HISTORY_COLLECTION",
            "chat_history",
        ),
        cross_session_memory_enabled=os.getenv(
            "RAG_ENABLE_CROSS_SESSION_MEMORY",
            "true",
        ).lower()
        in {"1", "true", "yes", "on"},
        celery_broker_url=os.getenv("RAG_CELERY_BROKER_URL", "filesystem://"),
        celery_queue_name=os.getenv("RAG_CELERY_QUEUE", "rag_ingestion"),
        celery_transport_role=os.getenv("RAG_CELERY_TRANSPORT_ROLE", "producer").lower(),
        celery_task_always_eager=os.getenv(
            "RAG_CELERY_TASK_ALWAYS_EAGER",
            "false",
        ).lower()
        in {"1", "true", "yes", "on"},
        docling_artifacts_dir=docling_artifacts_dir,
        docling_ocr_enabled=_env_bool("RAG_DOCLING_OCR", os.getenv("RAG_ENABLE_OCR", "true")),
        docling_table_structure_enabled=_env_bool("RAG_DOCLING_TABLE_STRUCTURE", "true"),
        web_search_backend=os.getenv("RAG_WEB_SEARCH_BACKEND", "duckduckgo"),
        web_search_region=os.getenv("RAG_WEB_SEARCH_REGION", "us-en"),
        web_search_max_results=int(os.getenv("RAG_WEB_SEARCH_MAX_RESULTS", "4")),
        web_search_score_threshold=float(os.getenv("RAG_WEB_SEARCH_SCORE_THRESHOLD", "0.3")),
        allowed_origins=_resolve_allowed_origins(os.getenv("RAG_ALLOWED_ORIGINS")),
        allowed_origin_regex=_resolve_allowed_origin_regex(os.getenv("RAG_ALLOWED_ORIGIN_REGEX")),
        topic_collection_prefix=os.getenv("RAG_TOPIC_COLLECTION_PREFIX", "topic__"),
        chunk_size=900,
        chunk_overlap=120,
        top_k=5,
    )


_SETTINGS = load_settings()


def get_settings() -> Settings:
    return _SETTINGS


def ensure_runtime_directories(settings: Settings) -> None:
    for path in (
        settings.data_dir,
        settings.uploads_dir,
        settings.chroma_path,
        settings.celery_root,
        settings.celery_queue_dir,
        settings.celery_reply_dir,
        settings.celery_control_dir,
        settings.celery_processed_dir,
        settings.docling_artifacts_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
