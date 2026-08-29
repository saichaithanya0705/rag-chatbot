from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import httpx

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

LOGGER = logging.getLogger(__name__)


def _load_local_embedding_model(model_name: str) -> Any:
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    try:
        from fastembed import TextEmbedding

        return TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    except Exception as error:
        LOGGER.warning("FastEmbed loading failed (%s), falling back to sentence_transformers.", error)
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")


@dataclass(frozen=True)
class NvidiaGenerationResult:
    response: str
    thinking: str | None = None


@dataclass(frozen=True)
class NvidiaStreamDelta:
    kind: Literal["thinking", "response"]
    content: str


class NvidiaClient:
    def __init__(
        self,
        base_url: str,
        embed_model: str,
        chat_model: str,
        *,
        nvidia_base_url: str = "https://integrate.api.nvidia.com/v1",
        nvidia_api_key: str = "",
        expected_embedding_dimensions: int | None = None,
        embed_timeout: float = 300.0,
        generate_timeout: float = 120.0,
        max_embed_concurrency: int = 4,
        max_generate_concurrency: int = 4,
        max_stream_concurrency: int = 4,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._embed_model = embed_model
        self._chat_model = chat_model
        self._nvidia_base_url = nvidia_base_url.rstrip("/")
        self._nvidia_api_key = nvidia_api_key or os.getenv("RAG_NVIDIA_API_KEY") or os.getenv("NVIDIA_API_KEY", "")
        self._expected_embedding_dimensions = expected_embedding_dimensions

        self._embed_model_local = None
        if not self._nvidia_api_key:
            LOGGER.info(
                "NVIDIA NIM API key missing. Local SentenceTransformer fallback will load on first embedding request."
            )
        else:
            LOGGER.info("NVIDIA NIM API key provided. Skipping local SentenceTransformer loading.")

        self._generate_client = httpx.AsyncClient(
            base_url=self._nvidia_base_url,
            timeout=httpx.Timeout(generate_timeout, connect=10.0, write=30.0, pool=30.0),
        )
        self._stream_client = httpx.AsyncClient(
            base_url=self._nvidia_base_url,
            timeout=None,
        )
        self._generate_semaphore = asyncio.Semaphore(max(1, max_generate_concurrency))
        self._stream_semaphore = asyncio.Semaphore(max(1, max_stream_concurrency))

    async def embed_texts(
        self,
        texts: list[str],
        *,
        input_type: Literal["query", "passage"] = "passage",
        timeout: float | None = None,
    ) -> list[list[float]]:
        is_cloud_model = any(
            self._embed_model.lower().startswith(prefix)
            for prefix in ("nvidia/", "snowflake/", "baai/", "nv-")
        )
        if self._nvidia_api_key and is_cloud_model:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._nvidia_api_key}",
            }
            payload = {
                "input": texts,
                "model": self._embed_model,
                "input_type": input_type,
            }
            if self._expected_embedding_dimensions:
                payload["dimensions"] = self._expected_embedding_dimensions

            request_timeout = None if timeout is None else httpx.Timeout(timeout, connect=10.0, pool=30.0)
            max_retries = 5
            retry_delay = 1.0
            last_error = None
            
            for attempt in range(1, max_retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=request_timeout) as client:
                        response = await client.post(
                            f"{self._nvidia_base_url}/embeddings",
                            json=payload,
                            headers=headers,
                        )
                        response.raise_for_status()
                        res_data = response.json()
                    
                    embeddings = [item["embedding"] for item in res_data["data"]]
                    self._validate_embedding_dimensions(embeddings)
                    return embeddings
                except Exception as error:
                    last_error = error
                    LOGGER.warning(
                        "NVIDIA NIM cloud embedding attempt %d/%d failed: %s",
                        attempt,
                        max_retries,
                        error,
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
            
            is_fallback_feasible = (
                self._expected_embedding_dimensions is None 
                or self._expected_embedding_dimensions == 384
            )
            if not is_fallback_feasible:
                LOGGER.error("NVIDIA NIM cloud embedding failed after %d retries. Fallback is not feasible due to dimension mismatch (expected 1024, fallback provides 384). Raising error.", max_retries)
                if last_error:
                    raise last_error
                raise RuntimeError("NVIDIA NIM cloud embedding failed and fallback was unfeasible.")
                
            LOGGER.warning("NVIDIA NIM cloud embedding failed after all retries; falling back to local SentenceTransformers.")

        loop = asyncio.get_running_loop()
        local_model = self._get_local_model()
        if hasattr(local_model, "embed"):
            embeddings_gen = await loop.run_in_executor(
                None,
                lambda: [emb.tolist() for emb in local_model.embed(texts)],
            )
            embeddings = embeddings_gen
        else:
            embeddings_nd = await loop.run_in_executor(
                None,
                lambda: local_model.encode(texts, convert_to_numpy=True),
            )
            embeddings = embeddings_nd.tolist()
        self._validate_embedding_dimensions(embeddings)
        return embeddings

    def _get_local_model(self) -> Any:
        if self._embed_model_local is None:
            model_name = self._embed_model
            if "nvidia" in model_name.lower():
                model_name = "sentence-transformers/all-MiniLM-L6-v2"
            LOGGER.info("Lazy loading local embedding model: %s", model_name)
            self._embed_model_local = _load_local_embedding_model(model_name)
        return self._embed_model_local

    def _validate_embedding_dimensions(self, embeddings: list[list[float]]) -> None:
        if self._expected_embedding_dimensions is None:
            return

        for index, embedding in enumerate(embeddings):
            actual_dimensions = len(embedding)
            if actual_dimensions != self._expected_embedding_dimensions:
                raise ValueError(
                    "Embedding model returned "
                    f"{actual_dimensions} dimensions for item {index}, expected "
                    f"{self._expected_embedding_dimensions}. Check config."
                )

    async def generate_answer(
        self,
        prompt: str,
        system_prompt: str,
        *,
        options: dict[str, Any] | None = None,
        images: list[Any] | None = None,
        include_thinking: bool = False,  # noqa: ARG002
        timeout: float | None = None,
    ) -> NvidiaGenerationResult:
        headers = {
            "Content-Type": "application/json",
        }
        if self._nvidia_api_key:
            headers["Authorization"] = f"Bearer {self._nvidia_api_key}"

        temperature = 0.2
        max_tokens = 1024
        stop = None
        if options:
            temperature = options.get("temperature", temperature)
            if "num_predict" in options:
                max_tokens = options["num_predict"]
            stop = options.get("stop", stop)

        # Build standard OpenAI messages payload
        messages = [{"role": "system", "content": system_prompt}]

        if images:
            content_list: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for img in images:
                # Support schema object or dict
                mime = getattr(img, "mime_type", None) or img.get("mimeType", None) or img.get("mime_type", "image/png")
                data = getattr(img, "data", None) or img.get("data", "")
                if data:
                    content_list.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{data}"
                        }
                    })
            messages.append({"role": "user", "content": content_list})
        else:
            messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if stop:
            payload["stop"] = stop

        request_timeout = None if timeout is None else httpx.Timeout(timeout, connect=10.0, write=30.0, pool=30.0)

        async with self._generate_semaphore:
            response = await self._generate_client.post(
                "/chat/completions",
                json=payload,
                headers=headers,
                timeout=request_timeout,
            )
            response.raise_for_status()
            res_data = response.json()

        response_text = res_data["choices"][0]["message"]["content"]
        return NvidiaGenerationResult(response=response_text)

    async def stream_answer(
        self,
        prompt: str,
        system_prompt: str,
        *,
        options: dict[str, Any] | None = None,
        images: list[Any] | None = None,
        include_thinking: bool = False,  # noqa: ARG002
        timeout: float | None = None,
    ) -> AsyncIterator[NvidiaStreamDelta]:
        headers = {
            "Content-Type": "application/json",
        }
        if self._nvidia_api_key:
            headers["Authorization"] = f"Bearer {self._nvidia_api_key}"

        temperature = 0.2
        max_tokens = 1024
        stop = None
        if options:
            temperature = options.get("temperature", temperature)
            if "num_predict" in options:
                max_tokens = options["num_predict"]
            stop = options.get("stop", stop)

        # Build standard OpenAI messages payload
        messages = [{"role": "system", "content": system_prompt}]

        if images:
            content_list: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for img in images:
                # Support schema object or dict
                mime = getattr(img, "mime_type", None) or img.get("mimeType", None) or img.get("mime_type", "image/png")
                data = getattr(img, "data", None) or img.get("data", "")
                if data:
                    content_list.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{data}"
                        }
                    })
            messages.append({"role": "user", "content": content_list})
        else:
            messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if stop:
            payload["stop"] = stop

        request_timeout = None if timeout is None else httpx.Timeout(timeout, connect=10.0, write=30.0, pool=30.0)

        async with self._stream_semaphore:
            async with self._stream_client.stream(
                "POST",
                "/chat/completions",
                json=payload,
                headers=headers,
                timeout=request_timeout,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            
                            if include_thinking:
                                reasoning = delta.get("reasoning_content", "") or delta.get("reasoning", "") or delta.get("thinking", "")
                                if reasoning:
                                    yield NvidiaStreamDelta(kind="thinking", content=reasoning)

                            content = delta.get("content", "")
                            if content:
                                yield NvidiaStreamDelta(kind="response", content=content)
                        except Exception:
                            continue

    async def aclose(self) -> None:
        await self._generate_client.aclose()
        await self._stream_client.aclose()
