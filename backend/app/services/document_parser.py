from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


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


class DocumentParser(Protocol):
    parser_name: str

    def parse(self, pdf_path: Path) -> ParsedDocument:
        """Parse a source PDF into normalized pages and structured blocks."""
        ...
