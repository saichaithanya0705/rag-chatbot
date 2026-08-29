from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import httpx
import numpy as np

from app.services.nvidia_client import (
    DEFAULT_LOCAL_EMBEDDING_DIMENSIONS,
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    NvidiaClient,
    resolve_embedding_model_id,
    resolve_embedding_runtime,
)


class _FakeFastEmbed:
    def __init__(self, dimensions: int = DEFAULT_LOCAL_EMBEDDING_DIMENSIONS) -> None:
        self._dimensions = dimensions

    def embed(self, texts: list[str]):
        return iter(np.full(self._dimensions, 0.1, dtype=float) for _ in texts)


class _FailingEmbeddingHttpClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):  # noqa: ANN001
        return False

    async def post(self, *args: object, **kwargs: object):  # noqa: ARG002
        raise httpx.ConnectError("offline")


class _MalformedEmbeddingResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"data": [{"embedding": [0.1, "invalid"]}]}


class _MalformedEmbeddingHttpClient:
    def __init__(self) -> None:
        self.post_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):  # noqa: ANN001
        return False

    async def post(self, *args: object, **kwargs: object) -> _MalformedEmbeddingResponse:  # noqa: ARG002
        self.post_calls += 1
        return _MalformedEmbeddingResponse()


class _StreamingResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):  # noqa: ANN001
        return False

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _StreamingHttpClient:
    def __init__(self, lines: list[str]) -> None:
        self._response = _StreamingResponse(lines)

    def stream(self, *args: object, **kwargs: object) -> _StreamingResponse:  # noqa: ARG002
        return self._response

    async def aclose(self) -> None:
        return None


class NvidiaClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_constructor_does_not_load_local_model_without_api_key(self) -> None:
        with patch(
            "app.services.nvidia_client._load_local_embedding_model",
            side_effect=AssertionError("constructor should not load local models"),
        ):
            client = NvidiaClient(
                base_url="https://example.com",
                embed_model="nvidia/llama-nemotron-embed-1b-v2",
                chat_model="meta/llama-3.2-11b-vision-instruct",
                nvidia_api_key="configured",
            )

            self.assertIsNone(client._embed_model_local)
            await client.aclose()

    async def test_local_model_loads_lazily_on_first_embedding_request(self) -> None:
        with patch.dict(
            os.environ,
            {"RAG_NVIDIA_API_KEY": "", "NVIDIA_API_KEY": ""},
            clear=False,
        ):
            with patch(
                "app.services.nvidia_client._load_local_embedding_model",
                return_value=_FakeFastEmbed(),
            ) as load_model:
                client = NvidiaClient(
                    base_url="https://example.com",
                    embed_model="nvidia/llama-nemotron-embed-1b-v2",
                    chat_model="meta/llama-3.2-11b-vision-instruct",
                    nvidia_api_key="",
                    expected_embedding_dimensions=1024,
                )

                self.assertIsNone(client._embed_model_local)
                embeddings = await client.embed_texts(["hello"], input_type="passage")

                self.assertEqual(len(embeddings[0]), DEFAULT_LOCAL_EMBEDDING_DIMENSIONS)
                load_model.assert_called_once_with(DEFAULT_LOCAL_EMBEDDING_MODEL)
                await client.aclose()

    def test_local_aliases_resolve_to_models_fastembed_can_load(self) -> None:
        self.assertEqual(
            resolve_embedding_model_id("all-minilm-l6-v2", use_cloud=False),
            "sentence-transformers/all-MiniLM-L6-v2",
        )

    def test_cloud_only_model_uses_explicit_local_default_without_api_key(self) -> None:
        self.assertEqual(
            resolve_embedding_model_id("nvidia/llama-nemotron-embed-1b-v2", use_cloud=False),
            DEFAULT_LOCAL_EMBEDDING_MODEL,
        )

    def test_cloud_model_without_api_key_uses_the_local_model_dimension_contract(self) -> None:
        runtime = resolve_embedding_runtime(
            "nvidia/llama-nemotron-embed-1b-v2",
            configured_dimensions=1024,
            use_cloud=False,
        )

        self.assertEqual(runtime.model, DEFAULT_LOCAL_EMBEDDING_MODEL)
        self.assertEqual(runtime.dimensions, DEFAULT_LOCAL_EMBEDDING_DIMENSIONS)
        self.assertFalse(runtime.uses_cloud)

    async def test_cloud_embedding_failure_never_mixes_in_a_local_model(self) -> None:
        client = NvidiaClient(
            base_url="https://example.com",
            embed_model="nvidia/llama-nemotron-embed-1b-v2",
            chat_model="meta/llama-3.2-11b-vision-instruct",
            nvidia_api_key="configured",
            expected_embedding_dimensions=1024,
        )
        with patch("app.services.nvidia_client.httpx.AsyncClient", return_value=_FailingEmbeddingHttpClient()):
            with patch("app.services.nvidia_client.asyncio.sleep", return_value=None):
                with patch(
                    "app.services.nvidia_client._load_local_embedding_model",
                    side_effect=AssertionError("cloud indexes must never use a different local model"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "refusing to mix"):
                        await client.embed_texts(["hello"])
        await client.aclose()

    async def test_malformed_cloud_embeddings_fail_without_retrying_or_falling_back(self) -> None:
        client = NvidiaClient(
            base_url="https://example.com",
            embed_model="nvidia/llama-nemotron-embed-1b-v2",
            chat_model="meta/llama-3.2-11b-vision-instruct",
            nvidia_api_key="configured",
            expected_embedding_dimensions=2,
        )
        malformed_client = _MalformedEmbeddingHttpClient()
        with patch("app.services.nvidia_client.httpx.AsyncClient", return_value=malformed_client):
            with self.assertRaisesRegex(ValueError, "non-numeric"):
                await client.embed_texts(["hello"])

        self.assertEqual(malformed_client.post_calls, 1)
        await client.aclose()

    async def test_malformed_stream_event_is_logged_and_does_not_hide_later_content(self) -> None:
        client = NvidiaClient(
            base_url="https://example.com",
            embed_model="nvidia/llama-nemotron-embed-1b-v2",
            chat_model="meta/llama-3.2-11b-vision-instruct",
            nvidia_api_key="configured",
        )
        await client._stream_client.aclose()
        client._stream_client = _StreamingHttpClient(
            [
                "data: not-json",
                'data: {"choices":[{"delta":{"content":"usable answer"}}]}',
                "data: [DONE]",
            ]
        )

        with self.assertLogs("app.services.nvidia_client", level="WARNING") as logs:
            deltas = [
                delta
                async for delta in client.stream_answer(
                    prompt="question",
                    system_prompt="system",
                )
            ]

        self.assertEqual([delta.content for delta in deltas], ["usable answer"])
        self.assertIn("Malformed NVIDIA stream event", "\n".join(logs.output))
        await client.aclose()


if __name__ == "__main__":
    unittest.main()
