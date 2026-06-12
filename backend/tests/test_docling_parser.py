from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.services.docling_parser import DoclingDocumentParser


class _FakeSize:
    def __init__(self, *, height: float) -> None:
        self.height = height


class _FakePage:
    def __init__(self, *, page_no: int, height: float) -> None:
        self.page_no = page_no
        self.size = _FakeSize(height=height)


class _FakeBBox:
    def __init__(self, *, l: float, t: float, r: float, b: float) -> None:
        self.l = l
        self.t = t
        self.r = r
        self.b = b


class _FakeProvenance:
    def __init__(self, *, page_no: int, bbox: _FakeBBox) -> None:
        self.page_no = page_no
        self.bbox = bbox
        self.charspan = (0, 0)


class _FakeLabel:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeLayer:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeTextItem:
    def __init__(self, *, text: str, label: str, page_no: int, bbox: _FakeBBox, layer: str = "body") -> None:
        self.text = text
        self.label = _FakeLabel(label)
        self.prov = [_FakeProvenance(page_no=page_no, bbox=bbox)]
        self.content_layer = _FakeLayer(layer)
        self.self_ref = f"#/{label}/{page_no}"


class _FakeTableItem(_FakeTextItem):
    def __init__(self, *, markdown: str, page_no: int, bbox: _FakeBBox) -> None:
        super().__init__(text="", label="table", page_no=page_no, bbox=bbox)
        self._markdown = markdown

    def export_to_markdown(self, doc: object) -> str:
        return self._markdown


class _FakeDoclingDocument:
    def __init__(self) -> None:
        self.pages = {1: _FakePage(page_no=1, height=800.0)}
        self._items = [
            _FakeTextItem(
                text="Document Title",
                label="section_header",
                page_no=1,
                bbox=_FakeBBox(l=20.0, t=30.0, r=500.0, b=60.0),
            ),
            _FakeTableItem(
                markdown="| Term | Meaning |\n| --- | --- |\n| RAG | Retrieval augmented generation |",
                page_no=1,
                bbox=_FakeBBox(l=20.0, t=90.0, r=500.0, b=180.0),
            ),
            _FakeTextItem(
                text="Page footer",
                label="page_footer",
                page_no=1,
                bbox=_FakeBBox(l=20.0, t=760.0, r=500.0, b=790.0),
                layer="furniture",
            ),
        ]

    def iterate_items(self) -> list[tuple[object, int]]:
        return [(item, 0) for item in self._items]


class _FakeRepeatingHeaderDocument:
    def __init__(self) -> None:
        self.pages = {
            1: _FakePage(page_no=1, height=800.0),
            2: _FakePage(page_no=2, height=800.0),
        }
        self._items = [
            _FakeTextItem(
                text="Local RAG Chat Sample Notes",
                label="text",
                page_no=1,
                bbox=_FakeBBox(l=20.0, t=25.0, r=500.0, b=45.0),
            ),
            _FakeTextItem(
                text="CPU scheduling body text.",
                label="text",
                page_no=1,
                bbox=_FakeBBox(l=20.0, t=140.0, r=500.0, b=190.0),
            ),
            _FakeTextItem(
                text="Local RAG Chat Sample Notes",
                label="text",
                page_no=2,
                bbox=_FakeBBox(l=20.0, t=25.0, r=500.0, b=45.0),
            ),
            _FakeTextItem(
                text="Memory management body text.",
                label="text",
                page_no=2,
                bbox=_FakeBBox(l=20.0, t=140.0, r=500.0, b=190.0),
            ),
        ]

    def iterate_items(self) -> list[tuple[object, int]]:
        return [(item, 0) for item in self._items]


class _FakeConversionResult:
    def __init__(self, document: object | None = None) -> None:
        self.document = document or _FakeDoclingDocument()


class _FakeConverter:
    def __init__(self, document: object | None = None) -> None:
        self._document = document

    def convert(self, source: Path) -> _FakeConversionResult:
        return _FakeConversionResult(self._document)


class DoclingDocumentParserTests(unittest.TestCase):
    def test_parse_preserves_body_blocks_tables_and_page_provenance(self) -> None:
        parser = DoclingDocumentParser(converter=_FakeConverter())

        with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf:
            parsed = parser.parse(Path(pdf.name))

        self.assertEqual(parsed.parser_name, "docling")
        self.assertEqual(len(parsed.pages), 1)
        page = parsed.pages[0]
        self.assertEqual(page.page_number, 1)
        self.assertEqual(
            page.text,
            "Document Title\n\n| Term | Meaning |\n| --- | --- |\n| RAG | Retrieval augmented generation |",
        )
        self.assertEqual([block.label for block in page.blocks], ["section_header", "table"])
        self.assertEqual(page.blocks[1].top, 90.0)
        self.assertEqual(page.blocks[1].bottom, 180.0)
        self.assertEqual(page.blocks[1].page_height, 800.0)
        self.assertEqual(page.blocks[1].bbox, {"l": 20.0, "t": 90.0, "r": 500.0, "b": 180.0})

    def test_parse_removes_repeated_margin_headers_from_docling_blocks(self) -> None:
        parser = DoclingDocumentParser(converter=_FakeConverter(_FakeRepeatingHeaderDocument()))

        with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf:
            parsed = parser.parse(Path(pdf.name))

        self.assertEqual([page.text for page in parsed.pages], [
            "CPU scheduling body text.",
            "Memory management body text.",
        ])

    def test_is_available_does_not_prepare_artifacts(self) -> None:
        class _NoDownloadParser(DoclingDocumentParser):
            def _prepare_artifacts(self, artifacts_path: Path) -> None:
                raise AssertionError("health checks must not download Docling models")

        with tempfile.TemporaryDirectory() as temp_dir:
            parser = _NoDownloadParser(artifacts_path=Path(temp_dir) / "models")

            self.assertTrue(parser.is_available())
            self.assertTrue(parser.ocr_pipeline_available())

    def test_fallback_availability_is_reported_when_docling_pipeline_is_missing(self) -> None:
        class _FallbackOnlyParser(DoclingDocumentParser):
            @staticmethod
            def _module_available(module_name: str) -> bool:
                return module_name == "pypdfium2"

        parser = _FallbackOnlyParser()

        self.assertTrue(parser.is_available())
        self.assertFalse(parser.ocr_pipeline_available())
        self.assertTrue(parser.fallback_parser_available())

    def test_is_available_prefers_fallback_without_importing_docling_pipeline(self) -> None:
        class _FallbackFirstParser(DoclingDocumentParser):
            @staticmethod
            def _module_available(module_name: str) -> bool:
                return module_name == "pypdfium2"

            @staticmethod
            def _import_docling_converter_types() -> tuple[object, object, object, object, object]:
                raise AssertionError("health capability checks must not import Docling")

        parser = _FallbackFirstParser()

        self.assertTrue(parser.is_available())

    def test_prepare_artifacts_downloads_only_enabled_pipeline_models(self) -> None:
        calls: list[tuple[Path, bool, bool]] = []

        class _RecordingParser(DoclingDocumentParser):
            def _download_required_models(self, artifacts_path: Path) -> None:
                calls.append((artifacts_path, self.ocr_enabled, self.table_structure_enabled))

        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_path = Path(temp_dir) / "docling-models"
            parser = _RecordingParser(
                artifacts_path=artifacts_path,
                ocr_enabled=True,
                table_structure_enabled=False,
            )

            parser._prepare_artifacts(artifacts_path)

            self.assertEqual(calls, [(artifacts_path, True, False)])
            self.assertTrue(artifacts_path.exists())


if __name__ == "__main__":
    unittest.main()
