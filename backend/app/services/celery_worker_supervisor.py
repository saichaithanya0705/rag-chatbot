from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from app.core.config import Settings, ensure_runtime_directories


class CeleryWorkerSupervisor:
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings
        self._process: subprocess.Popen[str] | None = None
        self._owns_process = False
        self._stdout_handle = None
        self._stderr_handle = None
        self._pid_path = settings.celery_root / "worker.pid"
        self._stdout_log_path = settings.celery_root / "worker.out.log"
        self._stderr_log_path = settings.celery_root / "worker.err.log"

    @property
    def enabled(self) -> bool:
        return (
            self._settings.celery_broker_url.startswith("filesystem://")
            and self._settings.celery_transport_role != "consumer"
            and not self._settings.celery_task_always_eager
        )

    def start(self) -> bool:
        if not self.enabled:
            return False

        ensure_runtime_directories(self._settings)
        existing_pid = self._read_pid()
        if existing_pid is not None and self._is_process_alive(existing_pid):
            return False

        self._remove_pid_file()
        self._stdout_handle = self._stdout_log_path.open("a", encoding="utf-8")
        self._stderr_handle = self._stderr_log_path.open("a", encoding="utf-8")
        worker_script = self._settings.backend_root / "scripts" / "run_celery_worker.py"
        env = os.environ.copy()
        env.setdefault("RAG_CELERY_TRANSPORT_ROLE", "consumer")
        env["RAG_CELERY_PID_FILE"] = str(self._pid_path)
        self._process = subprocess.Popen(
            [sys.executable, str(worker_script)],
            cwd=str(self._settings.backend_root),
            stdout=self._stdout_handle,
            stderr=self._stderr_handle,
            env=env,
            text=True,
            close_fds=True,
        )
        self._owns_process = True
        self._wait_until_ready()
        return True

    async def aclose(self) -> None:
        process = self._process
        if not self._owns_process or process is None:
            self._close_log_handles()
            return

        try:
            if process.poll() is None:
                process.terminate()
                await asyncio.to_thread(self._wait_or_kill, process)
        finally:
            self._remove_pid_file()
            self._close_log_handles()
            self._process = None
            self._owns_process = False

    def _wait_until_ready(self, timeout_seconds: float = 10.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            process = self._process
            if process is not None and process.poll() is not None:
                raise RuntimeError(self._startup_failure_message())
            worker_pid = self._read_pid()
            if worker_pid is not None and self._is_process_alive(worker_pid):
                return
            time.sleep(0.2)
        raise RuntimeError(self._startup_failure_message("Celery worker did not become ready in time."))

    @staticmethod
    def _wait_or_kill(process: subprocess.Popen[str], timeout_seconds: float = 10.0) -> None:
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout_seconds)

    def _startup_failure_message(self, fallback: str = "Celery worker exited during startup.") -> str:
        stderr_tail = self._tail_file(self._stderr_log_path)
        stdout_tail = self._tail_file(self._stdout_log_path)
        for candidate in (stderr_tail, stdout_tail):
            if candidate:
                return candidate
        return fallback

    @staticmethod
    def _tail_file(path: Path, max_lines: int = 20) -> str:
        if not path.exists():
            return ""
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-max_lines:]).strip()

    def _read_pid(self) -> int | None:
        if not self._pid_path.exists():
            return None
        try:
            return int(self._pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _remove_pid_file(self) -> None:
        self._pid_path.unlink(missing_ok=True)

    def _close_log_handles(self) -> None:
        for handle_name in ("_stdout_handle", "_stderr_handle"):
            handle = getattr(self, handle_name)
            if handle is not None:
                handle.close()
                setattr(self, handle_name, None)

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        except PermissionError:
            return True
        return True
