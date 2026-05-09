from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

os.environ.setdefault("RAG_CELERY_TRANSPORT_ROLE", "consumer")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.celery_app import celery_app
from app.core.config import ensure_runtime_directories, load_settings


def _write_pid_file() -> None:
    pid_file = os.getenv("RAG_CELERY_PID_FILE")
    if not pid_file:
        return
    path = Path(pid_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")


def _cleanup_pid_file() -> None:
    pid_file = os.getenv("RAG_CELERY_PID_FILE")
    if not pid_file:
        return
    path = Path(pid_file)
    if not path.exists():
        return
    try:
        if path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink(missing_ok=True)
    except OSError:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    settings = load_settings()
    ensure_runtime_directories(settings)
    _write_pid_file()
    atexit.register(_cleanup_pid_file)
    celery_app.worker_main(
        [
            "worker",
            "--loglevel=info",
            "--pool=solo",
            "--queues",
            settings.celery_queue_name,
        ]
    )
