from __future__ import annotations

import asyncio
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import load_settings
from app.services.nvidia_client import NvidiaClient


async def main() -> None:
    settings = load_settings()
    client = NvidiaClient(
        base_url=settings.nvidia_base_url,
        embed_model=settings.embed_model,
        chat_model=settings.chat_model,
        nvidia_base_url=settings.nvidia_base_url,
        nvidia_api_key=settings.nvidia_api_key,
        expected_embedding_dimensions=settings.embedding_dimensions,
    )

    embeddings = await client.embed_texts(["Round Robin scheduling"])
    answer = await client.generate_answer(
        prompt="Reply with exactly: ok",
        system_prompt="Return exactly the requested text.",
    )

    print(f"Embedding vector length: {len(embeddings[0])}")
    print(f"Generation result: {answer.response}")
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
