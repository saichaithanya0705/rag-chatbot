from __future__ import annotations

from collections import Counter
import importlib.util
import json
import logging
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Any, Iterable
import unicodedata

from app.services.document_parser import ParsedBlock, ParsedDocument, ParsedPage


LOGGER = logging.getLogger(__name__)
MARGIN_REPEAT_RATIO = 0.12
REPEATED_MARGIN_MIN_PAGES = 2


class OpenDataLoaderDocumentParser:
    """Parse digital PDFs with OpenDataLoader and a text-only PDFium fallback."""

    parser_name = "opendataloader_pdf"
    ocr_enabled = False

    def __init__(self) -> None:
        self._capability_lock = threading.Lock()
        self._opendataloader_available: bool | None = None
        self._fallback_parser_available: bool | None = None

    def is_available(self) -> bool:
        return self.opendataloader_available() or self.fallback_parser_available()

    def opendataloader_available(self) -> bool:
        with self._capability_lock:
            if self._opendataloader_available is None:
                self._opendataloader_available = (
                    self._module_available("opendataloader_pdf")
                    and shutil.which("java") is not None
                )
            return self._opendataloader_available

    def fallback_parser_available(self) -> bool:
        with self._capability_lock:
            if self._fallback_parser_available is None:
                self._fallback_parser_available = self._module_available("pypdfium2")
            return self._fallback_parser_available

    @staticmethod
    def ocr_pipeline_available() -> bool:
        return False

    def parse(self, pdf_path: Path) -> ParsedDocument:
        errors: list[Exception] = []
        if self.opendataloader_available():
            try:
                return self._parse_opendataloader(pdf_path)
            except Exception as error:  # noqa: BLE001
                errors.append(error)
                LOGGER.warning(
                    "OpenDataLoader failed for %s; trying the PDFium text fallback: %s",
                    pdf_path,
                    error,
                )

        if self.fallback_parser_available():
            try:
                return self._parse_fallback_pdfium(pdf_path)
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        detail = f" Last parser error: {errors[-1]}" if errors else ""
        raise ValueError(
            "No readable text was found in the PDF. OpenDataLoader core handles digital PDFs; "
            "image-only PDFs require a separately configured OCR pipeline, which this small-runtime "
            f"deployment intentionally does not include.{detail}"
        )

    def _parse_opendataloader(self, pdf_path: Path) -> ParsedDocument:
        import opendataloader_pdf

        with tempfile.TemporaryDirectory() as tmpdir:
            opendataloader_pdf.convert(
                input_path=str(pdf_path),
                output_dir=tmpdir,
                format="json",
                quiet=True,
                image_output="off",
            )
            json_files = sorted(Path(tmpdir).glob("*.json"))
            if len(json_files) != 1:
                raise ValueError(
                    f"OpenDataLoader produced {len(json_files)} JSON files for one input PDF; expected exactly one."
                )
            data = json.loads(json_files[0].read_text(encoding="utf-8"))

        page_sizes = self._pdf_page_sizes(pdf_path)
        pages = self._pages_from_opendataloader_json(data, page_sizes=page_sizes)
        if not any(page.blocks for page in pages):
            raise ValueError("OpenDataLoader JSON contained no readable text blocks.")
        return ParsedDocument(parser_name=self.parser_name, pages=pages)

    def _pages_from_opendataloader_json(
        self,
        data: Any,
        *,
        page_sizes: dict[int, tuple[float, float]] | None = None,
    ) -> list[ParsedPage]:
        if not isinstance(data, dict):
            return []

        page_sizes = page_sizes or {}
        blocks_by_page: dict[int, list[ParsedBlock]] = {}
        for element_index, element in enumerate(data.get("kids", [])):
            if not isinstance(element, dict):
                continue
            for block in self._blocks_from_element(
                element,
                page_sizes=page_sizes,
                source_path=f"#/kids/{element_index}",
            ):
                blocks_by_page.setdefault(block.page_number, []).append(block)

        blocks_by_page = self._filter_repeated_margin_blocks(blocks_by_page)
        declared_page_count = self._positive_int(data.get("number of pages"), 0)
        final_page_count = max(
            declared_page_count,
            max(page_sizes, default=0),
            max(blocks_by_page, default=0),
        )
        return [
            ParsedPage(page_number=page_number, blocks=blocks_by_page.get(page_number, []))
            for page_number in range(1, final_page_count + 1)
        ]

    def _blocks_from_element(
        self,
        element: dict[str, Any],
        *,
        page_sizes: dict[int, tuple[float, float]],
        source_path: str,
    ) -> list[ParsedBlock]:
        element_type = str(element.get("type", "text")).strip().lower()
        if element_type in {"image", "header", "footer"}:
            return []

        if element_type == "text block":
            return self._blocks_from_children(
                element.get("kids", []),
                page_sizes=page_sizes,
                source_path=f"{source_path}/kids",
            )

        if element_type == "table":
            text = self._extract_table_text(element)
        elif element_type == "list":
            text = self._extract_list_text(element)
        else:
            text = self._normalize_text(str(element.get("content", "")), preserve_newlines=True)

        if not text:
            return self._blocks_from_children(
                element.get("kids", []),
                page_sizes=page_sizes,
                source_path=f"{source_path}/kids",
            )

        page_number = self._positive_int(element.get("page number", element.get("page_number", 1)), 1)
        bbox = self._normalize_bbox(element.get("bounding box", element.get("bbox")))
        _page_width, page_height = page_sizes.get(page_number, self._size_from_bbox(bbox))
        label = element_type.replace(" ", "_") or "text"
        if element_type == "heading":
            level = self._positive_int(element.get("heading level", element.get("level", 0)), 0)
            label = f"heading_{level}" if level else "heading"

        return [
            ParsedBlock(
                text=text,
                page_number=page_number,
                label=label,
                top=float(bbox["t"]) if bbox else 0.0,
                bottom=float(bbox["b"]) if bbox else page_height,
                page_height=page_height,
                bbox=bbox,
                source_ref=source_path,
                content_layer="body",
            )
        ]

    def _blocks_from_children(
        self,
        children: Any,
        *,
        page_sizes: dict[int, tuple[float, float]],
        source_path: str,
    ) -> list[ParsedBlock]:
        if not isinstance(children, list):
            return []
        blocks: list[ParsedBlock] = []
        for child_index, child in enumerate(children):
            if isinstance(child, dict):
                blocks.extend(
                    self._blocks_from_element(
                        child,
                        page_sizes=page_sizes,
                        source_path=f"{source_path}/{child_index}",
                    )
                )
        return blocks

    @classmethod
    def _extract_table_text(cls, table: dict[str, Any]) -> str:
        lines: list[str] = []
        for row in table.get("rows", []):
            if not isinstance(row, dict):
                continue
            cells = [
                cls._element_text(cell)
                for cell in row.get("cells", [])
                if isinstance(cell, dict)
            ]
            lines.append(" | ".join(cell for cell in cells if cell))
        return "\n".join(line for line in lines if line)

    @classmethod
    def _extract_list_text(cls, node: dict[str, Any]) -> str:
        items = node.get("list items", [])
        if not isinstance(items, list):
            return ""
        ordered = str(node.get("numbering style", "")).lower() not in {"", "bullet", "unordered"}
        lines: list[str] = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            text = cls._element_text(item)
            if text:
                marker = f"{index}." if ordered else "-"
                lines.append(f"{marker} {text}")
        return "\n".join(lines)

    @classmethod
    def _element_text(cls, element: dict[str, Any]) -> str:
        direct = cls._normalize_text(str(element.get("content", "")), preserve_newlines=True)
        child_groups: Iterable[Any] = (
            element.get("kids", []),
            element.get("list items", []),
        )
        nested: list[str] = []
        for group in child_groups:
            if not isinstance(group, list):
                continue
            nested.extend(
                cls._element_text(child)
                for child in group
                if isinstance(child, dict)
            )
        return "\n".join(part for part in (direct, *nested) if part)

    def _parse_fallback_pdfium(self, pdf_path: Path) -> ParsedDocument:
        pdfium = self._import_pdfium_module()
        document = pdfium.PdfDocument(pdf_path)
        pages: list[ParsedPage] = []
        try:
            for index in range(len(document)):
                page = document[index]
                try:
                    width, height = page.get_size()
                    text_page = page.get_textpage()
                    try:
                        text = text_page.get_text_bounded()
                    finally:
                        text_page.close()
                    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
                    if not paragraphs and text.strip():
                        paragraphs = [text.strip()]
                    blocks = [
                        ParsedBlock(
                            text=paragraph,
                            page_number=index + 1,
                            label="paragraph",
                            top=0.0,
                            bottom=float(height),
                            page_height=float(height),
                            bbox={"l": 0.0, "t": 0.0, "r": float(width), "b": float(height)},
                            source_ref=f"#/pages/{index + 1}/blocks/{block_index}",
                            content_layer="body",
                        )
                        for block_index, paragraph in enumerate(paragraphs)
                    ]
                    pages.append(ParsedPage(page_number=index + 1, blocks=blocks))
                finally:
                    page.close()
        finally:
            document.close()

        if not any(page.blocks for page in pages):
            raise ValueError("PDFium found no digital text layer.")
        return ParsedDocument(parser_name="pypdfium2_fallback", pages=pages)

    def _pdf_page_sizes(self, pdf_path: Path) -> dict[int, tuple[float, float]]:
        pdfium = self._import_pdfium_module()
        document = pdfium.PdfDocument(pdf_path)
        sizes: dict[int, tuple[float, float]] = {}
        try:
            for index in range(len(document)):
                page = document[index]
                try:
                    width, height = page.get_size()
                    sizes[index + 1] = (float(width), float(height))
                finally:
                    page.close()
        finally:
            document.close()
        return sizes

    @staticmethod
    def _import_pdfium_module() -> Any:
        import pypdfium2 as pdfium

        return pdfium

    @staticmethod
    def _module_available(module_name: str) -> bool:
        return importlib.util.find_spec(module_name) is not None

    @staticmethod
    def _positive_int(value: Any, fallback: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return fallback
        return parsed if parsed > 0 else fallback

    @staticmethod
    def _normalize_bbox(raw_bbox: Any) -> dict[str, float] | None:
        if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
            left, bottom, right, top = (float(value) for value in raw_bbox)
            return {"l": left, "t": bottom, "r": right, "b": top}
        if isinstance(raw_bbox, dict) and {"l", "t", "r", "b"}.issubset(raw_bbox):
            return {key: float(raw_bbox[key]) for key in ("l", "t", "r", "b")}
        return None

    @staticmethod
    def _size_from_bbox(bbox: dict[str, float] | None) -> tuple[float, float]:
        if bbox is None:
            return (1.0, 1.0)
        return (max(1.0, bbox["r"]), max(1.0, bbox["b"]))

    @classmethod
    def _filter_repeated_margin_blocks(
        cls,
        blocks_by_page: dict[int, list[ParsedBlock]],
    ) -> dict[int, list[ParsedBlock]]:
        margin_text_counts: Counter[str] = Counter()
        for blocks in blocks_by_page.values():
            margin_text_counts.update(
                {
                    cls._normalized_repetition_key(block.text)
                    for block in blocks
                    if cls._is_margin_block(block)
                }
            )
        repeated = {
            text
            for text, count in margin_text_counts.items()
            if text and count >= REPEATED_MARGIN_MIN_PAGES
        }
        return {
            page_number: [
                block
                for block in blocks
                if not (
                    cls._is_margin_block(block)
                    and cls._normalized_repetition_key(block.text) in repeated
                )
            ]
            for page_number, blocks in blocks_by_page.items()
        }

    @staticmethod
    def _is_margin_block(block: ParsedBlock) -> bool:
        if block.bbox is None or block.page_height <= 0:
            return False
        return (
            block.top <= block.page_height * MARGIN_REPEAT_RATIO
            or block.bottom >= block.page_height * (1 - MARGIN_REPEAT_RATIO)
        )

    @staticmethod
    def _normalized_repetition_key(text: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())

    @staticmethod
    def _normalize_text(text: str, *, preserve_newlines: bool = False) -> str:
        normalized = unicodedata.normalize("NFKC", text or "").replace("\x00", " ")
        if preserve_newlines:
            return "\n".join(
                line
                for line in (" ".join(raw_line.split()) for raw_line in normalized.splitlines())
                if line
            )
        return " ".join(normalized.split())
