from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.services.opendataloader_parser import OpenDataLoaderDocumentParser


class OpenDataLoaderDocumentParserTests(unittest.TestCase):
    def test_parse_uses_pdfium_when_opendataloader_conversion_fails(self) -> None:
        parser = OpenDataLoaderDocumentParser()
        expected = object()
        pdf_path = Path("document.pdf")

        with (
            patch.object(parser, "opendataloader_available", return_value=True),
            patch.object(parser, "fallback_parser_available", return_value=True),
            patch.object(parser, "_parse_opendataloader", side_effect=RuntimeError("java failed")),
            patch.object(parser, "_parse_fallback_pdfium", return_value=expected) as fallback,
        ):
            parsed = parser.parse(pdf_path)

        self.assertIs(parsed, expected)
        fallback.assert_called_once_with(pdf_path)

    def test_parse_reports_the_last_engine_error_when_both_parsers_fail(self) -> None:
        parser = OpenDataLoaderDocumentParser()

        with (
            patch.object(parser, "opendataloader_available", return_value=True),
            patch.object(parser, "fallback_parser_available", return_value=True),
            patch.object(parser, "_parse_opendataloader", side_effect=RuntimeError("java failed")),
            patch.object(parser, "_parse_fallback_pdfium", side_effect=RuntimeError("pdfium failed")),
        ):
            with self.assertRaisesRegex(ValueError, "Last parser error: pdfium failed"):
                parser.parse(Path("document.pdf"))

    def test_structured_json_preserves_nested_text_tables_lists_and_provenance(self) -> None:
        parser = OpenDataLoaderDocumentParser()
        data = {
            "kids": [
                {
                    "type": "heading",
                    "id": 1,
                    "page number": 1,
                    "heading level": 2,
                    "bounding box": [72, 700, 300, 720],
                    "content": "System Overview",
                },
                {
                    "type": "text block",
                    "kids": [
                        {
                            "type": "paragraph",
                            "id": 2,
                            "page number": 1,
                            "bounding box": [72, 620, 500, 680],
                            "content": "Nested paragraph content",
                        }
                    ],
                },
                {
                    "type": "table",
                    "id": 3,
                    "page number": 1,
                    "bounding box": [72, 400, 500, 580],
                    "rows": [
                        {
                            "cells": [
                                {"kids": [{"type": "paragraph", "content": "Component"}]},
                                {"kids": [{"type": "paragraph", "content": "Role"}]},
                            ]
                        },
                        {
                            "cells": [
                                {"kids": [{"type": "paragraph", "content": "Parser"}]},
                                {"kids": [{"type": "paragraph", "content": "Extraction"}]},
                            ]
                        },
                    ],
                },
                {
                    "type": "list",
                    "id": 4,
                    "page number": 1,
                    "bounding box": [72, 250, 500, 360],
                    "numbering style": "bullet",
                    "list items": [
                        {"kids": [{"type": "paragraph", "content": "First item"}]},
                        {"kids": [{"type": "paragraph", "content": "Second item"}]},
                    ],
                },
            ]
        }

        pages = parser._pages_from_opendataloader_json(data, page_sizes={1: (612.0, 792.0)})

        self.assertEqual(len(pages), 1)
        self.assertEqual(
            [block.label for block in pages[0].blocks],
            ["heading_2", "paragraph", "table", "list"],
        )
        self.assertIn("Component | Role", pages[0].text)
        self.assertIn("Parser | Extraction", pages[0].text)
        self.assertIn("- First item", pages[0].text)
        self.assertEqual(pages[0].blocks[0].page_height, 792.0)
        self.assertEqual(pages[0].blocks[0].source_ref, "#/kids/0")

    def test_declared_blank_pages_are_preserved_for_page_number_alignment(self) -> None:
        parser = OpenDataLoaderDocumentParser()
        pages = parser._pages_from_opendataloader_json(
            {
                "number of pages": 2,
                "kids": [
                    {
                        "type": "paragraph",
                        "page number": 2,
                        "bounding box": [72, 600, 500, 620],
                        "content": "Page two content",
                    }
                ],
            },
            page_sizes={1: (612.0, 792.0), 2: (612.0, 792.0)},
        )

        self.assertEqual([page.page_number for page in pages], [1, 2])
        self.assertEqual(pages[0].text, "")
        self.assertEqual(pages[1].text, "Page two content")

    def test_duplicate_margin_text_on_one_page_is_not_treated_as_cross_page_repetition(self) -> None:
        parser = OpenDataLoaderDocumentParser()
        data = {
            "number of pages": 1,
            "kids": [
                {
                    "type": "paragraph",
                    "page number": 1,
                    "bounding box": [36, 760, 560, 780],
                    "content": "Important margin note",
                },
                {
                    "type": "paragraph",
                    "page number": 1,
                    "bounding box": [36, 730, 560, 750],
                    "content": "Important margin note",
                },
            ],
        }

        pages = parser._pages_from_opendataloader_json(data, page_sizes={1: (612.0, 792.0)})

        self.assertEqual(len(pages[0].blocks), 2)

    def test_repeated_margin_text_is_removed_but_body_text_is_retained(self) -> None:
        parser = OpenDataLoaderDocumentParser()
        data = {"kids": []}
        for page_number in (1, 2):
            data["kids"].extend(
                [
                    {
                        "type": "paragraph",
                        "page number": page_number,
                        "bounding box": [36, 760, 560, 780],
                        "content": "Repeated report title",
                    },
                    {
                        "type": "paragraph",
                        "page number": page_number,
                        "bounding box": [72, 300, 500, 340],
                        "content": f"Body page {page_number}",
                    },
                ]
            )

        pages = parser._pages_from_opendataloader_json(
            data,
            page_sizes={1: (612.0, 792.0), 2: (612.0, 792.0)},
        )

        self.assertEqual([page.text for page in pages], ["Body page 1", "Body page 2"])

    def test_capability_probe_does_not_execute_conversion(self) -> None:
        parser = OpenDataLoaderDocumentParser()
        with patch.object(parser, "_parse_opendataloader", side_effect=AssertionError("must not parse")):
            self.assertIsInstance(parser.is_available(), bool)

    def test_parse_reads_the_exact_json_output_contract(self) -> None:
        parser = OpenDataLoaderDocumentParser()
        payload = {
            "kids": [
                {
                    "type": "paragraph",
                    "id": 8,
                    "page number": 1,
                    "bounding box": [72, 600, 500, 620],
                    "content": "Converted content",
                }
            ]
        }

        def fake_convert(**kwargs: object) -> None:
            Path(str(kwargs["output_dir"]), "result.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )

        with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf_file:
            with patch("opendataloader_pdf.convert", side_effect=fake_convert):
                with patch.object(parser, "_pdf_page_sizes", return_value={1: (612.0, 792.0)}):
                    parsed = parser._parse_opendataloader(Path(pdf_file.name))

        self.assertEqual(parsed.parser_name, "opendataloader_pdf")
        self.assertEqual(parsed.pages[0].text, "Converted content")


if __name__ == "__main__":
    unittest.main()
