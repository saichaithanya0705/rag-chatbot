from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4


ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class OcrService:
    def __init__(
        self,
        *,
        enabled: bool,
        command: str,
        output_dir: Path,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._enabled = enabled
        self._command = command
        self._output_dir = output_dir
        self._timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return self._enabled

    def is_available(self) -> bool:
        return self._enabled and self._resolve_command_path() is not None

    async def extract_pdf_texts(self, pdf_path: Path) -> list[str]:
        if not self._enabled:
            raise RuntimeError("OCR support is disabled.")

        command_path = self._resolve_command_path()
        if command_path is None:
            raise RuntimeError(
                f"OCR fallback requires '{self._command}'. Install surya-ocr to index scanned PDFs.",
            )

        self._output_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=f"{pdf_path.stem}-{uuid4().hex[:8]}-", dir=self._output_dir))

        try:
            process = await asyncio.create_subprocess_exec(
                command_path,
                str(pdf_path),
                "--output_dir",
                str(temp_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self._timeout_seconds,
                )
            except asyncio.TimeoutError as error:
                await self._terminate_process(process)
                raise RuntimeError("Surya OCR timed out before it produced readable output.") from error
            except asyncio.CancelledError:
                await self._terminate_process(process)
                raise
            if process.returncode != 0:
                raise RuntimeError(
                    self._summarize_failure(
                        stdout.decode("utf-8", errors="ignore"),
                        stderr.decode("utf-8", errors="ignore"),
                    )
                )

            results_path = self._resolve_results_path(temp_dir, pdf_path)
            payload = json.loads(results_path.read_text(encoding="utf-8"))
            pages = payload.get(pdf_path.stem)
            if pages is None and payload:
                pages = next(iter(payload.values()))

            if not isinstance(pages, list):
                raise RuntimeError("Surya OCR did not return page results.")

            page_texts = [self._page_text(page_payload) for page_payload in pages]
            if not any(text.strip() for text in page_texts):
                raise RuntimeError("Surya OCR completed, but no readable text was detected.")

            return page_texts
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    async def _terminate_process(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    @staticmethod
    def _resolve_results_path(temp_dir: Path, pdf_path: Path) -> Path:
        candidates = [
            temp_dir / "results.json",
            temp_dir / pdf_path.stem / "results.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise RuntimeError("Surya OCR results.json was not produced.")

    @staticmethod
    def _page_text(page_payload: object) -> str:
        if not isinstance(page_payload, dict):
            return ""

        text_lines = page_payload.get("text_lines", [])
        if isinstance(text_lines, list):
            lines = [
                str(line.get("text", "")).strip()
                for line in text_lines
                if isinstance(line, dict) and str(line.get("text", "")).strip()
            ]
            if lines:
                return "\n".join(lines)

        fallback_text = str(page_payload.get("text", "")).strip()
        return fallback_text

    def _resolve_command_path(self) -> str | None:
        candidates = [self._command]
        command_path = Path(self._command)
        if command_path.suffix == "" and sys.platform.startswith("win"):
            candidates.append(f"{self._command}.exe")

        scripts_dir = Path(sys.executable).resolve().parent
        for candidate in candidates:
            explicit_path = Path(candidate)
            if explicit_path.is_file():
                return str(explicit_path)

            bundled_script = scripts_dir / candidate
            if bundled_script.exists():
                return str(bundled_script)

            resolved = shutil.which(candidate)
            if resolved:
                return resolved

        return None

    @classmethod
    def _summarize_failure(cls, stdout: str, stderr: str) -> str:
        combined = "\n".join(part for part in (stderr, stdout) if part).strip()
        cleaned = cls._strip_ansi(combined)
        if "SuryaDecoderConfig" in cleaned and "pad_token_id" in cleaned:
            return (
                "Surya OCR dependency mismatch. Install a compatible Transformers 4.x "
                "release such as 4.57.3 instead of Transformers 5.x."
            )

        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        if not lines:
            return "Surya OCR exited with a non-zero status."

        for line in reversed(lines):
            if "Traceback" in line or line.startswith("Downloading "):
                continue
            return line[:300]

        return lines[-1][:300]

    @staticmethod
    def _strip_ansi(value: str) -> str:
        return ANSI_ESCAPE_PATTERN.sub("", value).replace("\r", "\n")
