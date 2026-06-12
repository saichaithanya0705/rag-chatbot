from __future__ import annotations

import os
import asyncio
import unittest
from unittest.mock import patch

import numpy as np

from app.services.nvidia_client import NvidiaClient


class _FakeSentenceTransformer:
    def encode(self, texts: list[str], convert_to_numpy: bool = True):  # noqa: ARG002
        return np.asarray([[0.1, 0.2, 0.3] for _ in texts], dtype=float)


class NvidiaClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_constructor_does_not_load_local_model_without_api_key(self) -> None:
        with patch(
            "app.services.nvidia_client._load_sentence_transformer",
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
                "app.services.nvidia_client._load_sentence_transformer",
                return_value=_FakeSentenceTransformer(),
            ) as load_model:
                client = NvidiaClient(
                    base_url="https://example.com",
                    embed_model="nvidia/llama-nemotron-embed-1b-v2",
                    chat_model="meta/llama-3.2-11b-vision-instruct",
                    nvidia_api_key="",
                    expected_embedding_dimensions=3,
                )

                self.assertIsNone(client._embed_model_local)
                embeddings = await client.embed_texts(["hello"], input_type="passage")

                self.assertEqual(embeddings, [[0.1, 0.2, 0.3]])
                load_model.assert_called_once_with("sentence-transformers/all-MiniLM-L6-v2")
                await client.aclose()


if __name__ == "__main__":
    unittest.main()
