from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any
import unicodedata


MARGIN_REPEAT_RATIO = 0.12
REPEATED_MARGIN_MIN_PAGES = 2


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    page_number: int
    label: str
    top: float
    bottom: float
    page_height: float
    bbox: dict[str, float] | None = None
    source_ref: str | None = None
    content_layer: str | None = None


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    blocks: list[ParsedBlock]

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks if block.text.strip())


@dataclass(frozen=True)
class ParsedDocument:
    parser_name: str
    pages: list[ParsedPage]


class DoclingDocumentParser:
    parser_name = "docling"

    def __init__(
        self,
        *,
        converter: Any | None = None,
        ocr_enabled: bool = True,
        table_structure_enabled: bool = True,
        artifacts_path: Path | None = None,
    ) -> None:
        self._converter = converter
        self._ocr_enabled = ocr_enabled
        self._table_structure_enabled = table_structure_enabled
        self._artifacts_path = artifacts_path
        self._converter_lock = threading.Lock()

    @property
    def ocr_enabled(self) -> bool:
        return self._ocr_enabled

    @property
    def table_structure_enabled(self) -> bool:
        return self._table_structure_enabled

    @property
    def artifacts_path(self) -> Path | None:
        return self._artifacts_path

    def is_available(self) -> bool:
        try:
            self._import_docling_converter_types()
        except ImportError:
            return False
        return True

    def parse(self, pdf_path: Path) -> ParsedDocument:
        converter = self._ensure_converter()
        result = converter.convert(pdf_path)
        document = result.document
        pages = self._pages_from_docling_document(document)
        if not pages:
            raise ValueError("Docling did not extract readable page content from the PDF.")
        return ParsedDocument(parser_name=self.parser_name, pages=pages)

    def _ensure_converter(self) -> Any:
        if self._converter is None:
            with self._converter_lock:
                if self._converter is None:
                    self._converter = self._build_converter()
        return self._converter

    def _build_converter(self) -> Any:
        try:
            InputFormat, PdfPipelineOptions, TableStructureOptions, DocumentConverter, PdfFormatOption = (
                self._import_docling_converter_types()
            )
        except ImportError as error:
            raise RuntimeError(
                "Docling parser requires the 'docling' package. Install backend requirements before ingesting PDFs."
            ) from error

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = self._ocr_enabled
        pipeline_options.do_table_structure = self._table_structure_enabled
        if self._artifacts_path is not None:
            self._prepare_artifacts(self._artifacts_path)
            pipeline_options.artifacts_path = self._artifacts_path
        if self._table_structure_enabled:
            pipeline_options.table_structure_options = TableStructureOptions(do_cell_matching=True)

        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            }
        )

    @staticmethod
    def _import_docling_converter_types() -> tuple[Any, Any, Any, Any, Any]:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        return InputFormat, PdfPipelineOptions, TableStructureOptions, DocumentConverter, PdfFormatOption

    def _prepare_artifacts(self, artifacts_path: Path) -> None:
        artifacts_path.mkdir(parents=True, exist_ok=True)
        try:
            self._download_required_models(artifacts_path)
        except Exception as error:
            raise RuntimeError(
                f"Docling could not prepare local model artifacts at '{artifacts_path}'. "
                "Check network access on first run, or prefetch Docling models into RAG_DOCLING_ARTIFACTS_DIR."
            ) from error

    def _download_required_models(self, artifacts_path: Path) -> None:
        from docling.utils.model_downloader import download_models

        download_models(
            output_dir=artifacts_path,
            progress=False,
            with_layout=True,
            with_tableformer=self._table_structure_enabled,
            with_tableformer_v2=False,
            with_code_formula=False,
            with_picture_classifier=False,
            with_rapidocr=self._ocr_enabled,
            with_easyocr=False,
        )

    def _pages_from_docling_document(self, document: Any) -> list[ParsedPage]:
        blocks_by_page: dict[int, list[ParsedBlock]] = {
            int(page_number): []
            for page_number in sorted(getattr(document, "pages", {}) or {})
        }

        for item, _level in document.iterate_items():
            if self._is_furniture_item(item):
                continue

            text = self._item_text(item, document)
            if not text:
                continue

            page_number, bbox, page_height = self._item_provenance(item, document)
            if page_number is None:
                continue

            label = self._item_label(item)
            blocks_by_page.setdefault(page_number, []).append(
                ParsedBlock(
                    text=text,
                    page_number=page_number,
                    label=label,
                    top=float(bbox["t"]) if bbox else 0.0,
                    bottom=float(bbox["b"]) if bbox else page_height,
                    page_height=page_height,
                    bbox=bbox,
                    source_ref=self._source_ref(item),
                    content_layer=self._content_layer(item),
                )
            )

        blocks_by_page = self._filter_repeated_margin_blocks(blocks_by_page)

        return [
            ParsedPage(page_number=page_number, blocks=blocks)
            for page_number, blocks in sorted(blocks_by_page.items())
            if blocks
        ]

    @classmethod
    def _item_text(cls, item: Any, document: Any) -> str:
        if cls._item_label(item) == "table" and hasattr(item, "export_to_markdown"):
            try:
                return cls._normalize_text(item.export_to_markdown(document), preserve_newlines=True)
            except TypeError:
                return cls._normalize_text(item.export_to_markdown(), preserve_newlines=True)

        text = getattr(item, "text", "")
        return cls._normalize_text(str(text), preserve_newlines=True)

    @staticmethod
    def _item_label(item: Any) -> str:
        label = getattr(item, "label", "")
        value = getattr(label, "value", label)
        return str(value or "text").strip().lower()

    @staticmethod
    def _content_layer(item: Any) -> str | None:
        layer = getattr(item, "content_layer", None)
        if layer is None:
            return None
        return str(getattr(layer, "value", layer)).strip().lower() or None

    @classmethod
    def _is_furniture_item(cls, item: Any) -> bool:
        layer = cls._content_layer(item)
        label = cls._item_label(item)
        return layer == "furniture" or label in {"page_header", "page_footer"}

    @classmethod
    def _filter_repeated_margin_blocks(
        cls,
        blocks_by_page: dict[int, list[ParsedBlock]],
    ) -> dict[int, list[ParsedBlock]]:
        margin_text_counts = Counter(
            cls._normalized_repetition_key(block.text)
            for blocks in blocks_by_page.values()
            for block in blocks
            if cls._is_margin_block(block)
        )
        repeated_margin_texts = {
            text
            for text, count in margin_text_counts.items()
            if text and count >= REPEATED_MARGIN_MIN_PAGES
        }
        if not repeated_margin_texts:
            return blocks_by_page

        return {
            page_number: [
                block
                for block in blocks
                if not (
                    cls._is_margin_block(block)
                    and cls._normalized_repetition_key(block.text) in repeated_margin_texts
                )
            ]
            for page_number, blocks in blocks_by_page.items()
        }

    @staticmethod
    def _is_margin_block(block: ParsedBlock) -> bool:
        if block.bbox is None or block.page_height <= 0:
            return False
        top_margin = block.page_height * MARGIN_REPEAT_RATIO
        bottom_margin = block.page_height * (1 - MARGIN_REPEAT_RATIO)
        return block.top <= top_margin or block.bottom >= bottom_margin

    @staticmethod
    def _normalized_repetition_key(text: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())

    @classmethod
    def _item_provenance(cls, item: Any, document: Any) -> tuple[int | None, dict[str, float] | None, float]:
        provenance_items = list(getattr(item, "prov", []) or [])
        provenance = provenance_items[0] if provenance_items else None
        if provenance is None:
            return None, None, 1.0

        page_number = int(getattr(provenance, "page_no", 0) or 0)
        if page_number <= 0:
            return None, None, 1.0

        page = (getattr(document, "pages", {}) or {}).get(page_number)
        page_height = float(getattr(getattr(page, "size", None), "height", 1.0) or 1.0)

        raw_bbox = getattr(provenance, "bbox", None)
        bbox = cls._bbox_dict(raw_bbox)
        return page_number, bbox, page_height

    @staticmethod
    def _bbox_dict(raw_bbox: Any) -> dict[str, float] | None:
        if raw_bbox is None:
            return None
        values = {
            "l": getattr(raw_bbox, "l", None),
            "t": getattr(raw_bbox, "t", None),
            "r": getattr(raw_bbox, "r", None),
            "b": getattr(raw_bbox, "b", None),
        }
        if any(value is None for value in values.values()):
            return None
        return {key: float(value) for key, value in values.items() if value is not None}

    @staticmethod
    def _source_ref(item: Any) -> str | None:
        value = getattr(item, "self_ref", None)
        return str(value) if value is not None else None

    @staticmethod
    def _normalize_text(text: str, *, preserve_newlines: bool = False) -> str:
        normalized = unicodedata.normalize("NFKC", text or "")
        normalized = normalized.replace("\x00", " ")
        if preserve_newlines:
            normalized_lines = [
                " ".join(line.split())
                for line in normalized.splitlines()
                if " ".join(line.split())
            ]
            return "\n".join(normalized_lines)
        return " ".join(normalized.split())
