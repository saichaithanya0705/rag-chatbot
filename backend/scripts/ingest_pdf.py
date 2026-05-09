from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import ensure_runtime_directories, load_settings
from app.services.container import build_container


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a PDF into the local RAG store.")
    parser.add_argument("pdf_path", help="Path to a PDF file.")
    parser.add_argument("--user-id", default="default", help="User namespace to ingest into.")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).expanduser().resolve()
    settings = load_settings()
    ensure_runtime_directories(settings)

    container = build_container(settings)
    result = await container.ingestion_service.ingest_pdf(pdf_path, user_id=args.user_id)
    print(
        f"Ingested {result.pdf_name} with {result.page_count} pages and {result.chunk_count} chunks."
    )


if __name__ == "__main__":
    asyncio.run(main())
