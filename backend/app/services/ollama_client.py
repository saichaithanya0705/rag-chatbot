from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from typing import Literal

import httpx


@dataclass(frozen=True)
class OllamaGenerationResult:
    response: str
    thinking: str | None = None


@dataclass(frozen=True)
class OllamaStreamDelta:
    kind: Literal["thinking", "response"]
    content: str


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        embed_model: str,
        chat_model: str,
        *,
        expected_embedding_dimensions: int | None = None,
        embed_timeout: float = 300.0,
        generate_timeout: float = 120.0,
        max_embed_concurrency: int = 4,
        max_generate_concurrency: int = 2,
        max_stream_concurrency: int = 2,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._embed_model = embed_model
        self._chat_model = chat_model
        self._expected_embedding_dimensions = expected_embedding_dimensions
        self._embed_client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._build_timeout(embed_timeout),
        )
        self._generate_client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._build_timeout(generate_timeout),
        )
        self._stream_client = httpx.AsyncClient(base_url=self._base_url, timeout=None)
        self._embed_semaphore = asyncio.Semaphore(max(1, max_embed_concurrency))
        self._generate_semaphore = asyncio.Semaphore(max(1, max_generate_concurrency))
        self._stream_semaphore = asyncio.Semaphore(max(1, max_stream_concurrency))

    @staticmethod
    def _build_timeout(total_seconds: float) -> httpx.Timeout:
        return httpx.Timeout(total_seconds, connect=10.0, write=30.0, pool=30.0)

    async def embed_texts(
        self,
        texts: list[str],
        *,
        timeout: float | None = None,
    ) -> list[list[float]]:
        async with self._embed_semaphore:
            response = await self._post(
                "/api/embed",
                {
                    "model": self._embed_model,
                    "input": texts,
                },
                client=self._embed_client,
                timeout=timeout,
            )
        embeddings = response["embeddings"]
        self._validate_embedding_dimensions(embeddings)
        return embeddings

    def _validate_embedding_dimensions(self, embeddings: list[list[float]]) -> None:
        if self._expected_embedding_dimensions is None:
            return

        for index, embedding in enumerate(embeddings):
            actual_dimensions = len(embedding)
            if actual_dimensions != self._expected_embedding_dimensions:
                raise ValueError(
                    "Embedding model returned "
                    f"{actual_dimensions} dimensions for item {index}, expected "
                    f"{self._expected_embedding_dimensions}. Check RAG_OLLAMA_EMBED_MODEL "
                    "and RAG_EMBEDDING_DIMENSIONS."
                )

    async def generate_answer(
        self,
        prompt: str,
        system_prompt: str,
        *,
        options: dict[str, Any] | None = None,
        include_thinking: bool = False,
        timeout: float | None = None,
    ) -> OllamaGenerationResult:
        payload: dict[str, Any] = {
            "model": self._chat_model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "think": include_thinking,
        }
        if options:
            payload["options"] = options

        async with self._generate_semaphore:
            response = await self._post(
                "/api/generate",
                payload,
                client=self._generate_client,
                timeout=timeout,
            )
        thinking = str(response.get("thinking", "")).strip() or None
        return OllamaGenerationResult(
            response=str(response["response"]).strip(),
            thinking=thinking,
        )

    async def stream_answer(
        self,
        prompt: str,
        system_prompt: str,
        *,
        options: dict[str, Any] | None = None,
        include_thinking: bool = False,
        timeout: float | None = None,
    ) -> AsyncIterator[OllamaStreamDelta]:
        payload = {
            "model": self._chat_model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": True,
            "think": include_thinking,
        }
        if options:
            payload["options"] = options
        request_timeout = None if timeout is None else self._build_timeout(timeout)

        async with self._stream_semaphore:
            async with self._stream_client.stream(
                "POST",
                "/api/generate",
                json=payload,
                timeout=request_timeout,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    thinking = str(chunk.get("thinking", ""))
                    if thinking:
                        yield OllamaStreamDelta(kind="thinking", content=thinking)
                    content = str(chunk.get("response", ""))
                    if content:
                        yield OllamaStreamDelta(kind="response", content=content)
                    if chunk.get("done"):
                        break

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        client: httpx.AsyncClient,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        request_timeout = None if timeout is None else self._build_timeout(timeout)
        response = await client.post(path, json=payload, timeout=request_timeout)
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._embed_client.aclose()
        await self._generate_client.aclose()
        await self._stream_client.aclose()
