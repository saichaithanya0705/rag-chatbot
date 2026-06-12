from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.core.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_data_dir_can_be_overridden_for_deployments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"RAG_DATA_DIR": temp_dir}, clear=False):
                settings = load_settings()

        expected = Path(temp_dir)
        self.assertEqual(settings.data_dir, expected)
        self.assertEqual(settings.uploads_dir, expected / "uploads")
        self.assertEqual(settings.sqlite_path, expected / "app.db")
        self.assertEqual(settings.chroma_path, expected / "chroma")
        self.assertEqual(settings.kg_path, expected / "kg.pkl")
        self.assertEqual(settings.docling_artifacts_dir, expected / "docling-models")

    def test_explicit_docling_artifacts_dir_overrides_data_dir_default(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as artifacts_dir:
            with patch.dict(
                os.environ,
                {
                    "RAG_DATA_DIR": data_dir,
                    "RAG_DOCLING_ARTIFACTS_DIR": artifacts_dir,
                },
                clear=False,
            ):
                settings = load_settings()

        self.assertEqual(settings.data_dir, Path(data_dir))
        self.assertEqual(settings.docling_artifacts_dir, Path(artifacts_dir))

    def test_chat_rate_limits_default_to_strict_demo_values(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings()

        self.assertEqual(settings.chat_rate_limit_per_minute, 3)
        self.assertEqual(settings.chat_rate_limit_per_hour, 12)

    def test_chat_rate_limits_can_be_overridden_for_deployments(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RAG_CHAT_RATE_LIMIT_PER_MINUTE": "2",
                "RAG_CHAT_RATE_LIMIT_PER_HOUR": "8",
            },
            clear=False,
        ):
            settings = load_settings()

        self.assertEqual(settings.chat_rate_limit_per_minute, 2)
        self.assertEqual(settings.chat_rate_limit_per_hour, 8)


if __name__ == "__main__":
    unittest.main()
