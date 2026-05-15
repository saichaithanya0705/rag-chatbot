from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
import unicodedata

from app.services.document_parser import ParsedBlock


QUESTION_HEADER_PATTERN = re.compile(
    r"(?ims)(?:^|\n{1,2}|(?<=[.?!]))\s*(?:question\s+\d+[:.)-]*|\d{1,3}[.)]|q\s*[:.)-])\s*(?P<question>.*?(?:\?|[.:](?=\n{2,}|$)))"
)
LOW_SIGNAL_QA_PATTERNS = (
    "copyright by",
    "register now",
    "live version of the page",
    "live masterclass",
    "masterclass",
    "masterclasses",
    "click here",
    "contents",
)
EMBEDDED_QUESTION_MARKER_PATTERN = re.compile(
    r"\s+((?:question\s+\d+[:.)-]*|\d{1,3}[.)]|q\s*[:.)-]))\s+(?=[A-Z0-9])",
    re.IGNORECASE,
)
QA_NOISE_LINE_PATTERN = re.compile(
    r"(?im)^\s*(?:page\s+\d+|[^ \n\r]*\s*copyright\b.*)$"
)


@dataclass(frozen=True)
class PageChunkDraft:
    text: str
    metadata: dict[str, object]


class PageTextSplitter(Protocol):
    async def split_text(
        self,
        text: str,
        *,
        threshold: float | None = None,
        blocks: list[str] | None = None,
    ) -> list[str]:
        ...


class IngestionChunkBuilder:
    def __init__(self, *, text_splitter: PageTextSplitter) -> None:
        self._text_splitter = text_splitter

    async def build_page_chunk_drafts(
        self,
        *,
        page_number: int,
        page_text: str,
        page_blocks: list[ParsedBlock],
        threshold: float | None,
        qa_document: bool,
        carryover_question: str | None,
    ) -> tuple[list[PageChunkDraft], str | None]:
        block_texts = [block.text for block in page_blocks if block.text.strip()]
        if not qa_document:
            page_chunks = await self._text_splitter.split_text(
                page_text,
                threshold=threshold,
                blocks=block_texts,
            )
            return [PageChunkDraft(text=chunk, metadata={}) for chunk in page_chunks], None

        qa_page_text = self._prepare_qa_page_text(
            "\n\n".join(block_texts).strip() or page_text.strip()
        )
        question_sections = self._qa_question_sections(qa_page_text)
        if self._should_skip_qa_page(
            qa_page_text,
            page_number=page_number,
            question_sections=question_sections,
        ):
            return [], None

        drafts: list[PageChunkDraft] = []
        next_carryover_question: str | None = None

        if not question_sections:
            if not carryover_question or not qa_page_text:
                return [], None

            answer_chunks = await self._text_splitter.split_text(
                qa_page_text,
                threshold=threshold,
            )
            return (
                [
                    PageChunkDraft(
                        text=self._question_context_chunk(
                            question=carryover_question,
                            body=chunk,
                        ),
                        metadata={
                            "content_type": "qa",
                            "qa_question": carryover_question,
                            "qa_continuation": True,
                        },
                    )
                    for chunk in answer_chunks
                ],
                carryover_question,
            )

        prefix_text = qa_page_text[: question_sections[0][0]].strip()
        if carryover_question and prefix_text and not self._is_low_signal_fragment(prefix_text):
            prefix_chunks = await self._text_splitter.split_text(
                prefix_text,
                threshold=threshold,
            )
            drafts.extend(
                PageChunkDraft(
                    text=self._question_context_chunk(
                        question=carryover_question,
                        body=chunk,
                    ),
                    metadata={
                        "content_type": "qa",
                        "qa_question": carryover_question,
                        "qa_continuation": True,
                    },
                )
                for chunk in prefix_chunks
            )

        for index, (start, end, question) in enumerate(question_sections):
            section_text = qa_page_text[start:end].strip()
            if not section_text:
                continue
            nested_sections = self._split_nested_qa_sections(
                section_text=section_text,
                fallback_question=question,
            )
            for nested_question, nested_text in nested_sections:
                section_chunks = await self._text_splitter.split_text(
                    nested_text,
                    threshold=threshold,
                )
                for chunk in section_chunks:
                    if nested_question.lower() not in chunk[: max(len(nested_question) + 32, 96)].lower():
                        chunk = self._question_context_chunk(question=nested_question, body=chunk)
                    drafts.append(
                        PageChunkDraft(
                            text=chunk,
                            metadata={
                                "content_type": "qa",
                                "qa_question": nested_question,
                            },
                        )
                    )

            carryover_question_for_section, carryover_text_for_section = nested_sections[-1]
            if index == len(question_sections) - 1 and self._should_carryover_question(
                question=carryover_question_for_section,
                section_text=carryover_text_for_section,
                page_text=qa_page_text,
                section_end=end,
            ):
                next_carryover_question = carryover_question_for_section

        return drafts, next_carryover_question

    @classmethod
    def is_question_answer_document(cls, page_blocks_by_page: list[list[ParsedBlock]]) -> bool:
        if not page_blocks_by_page:
            return False
        sample_pages = page_blocks_by_page[: min(len(page_blocks_by_page), 12)]
        question_total = 0
        question_pages = 0
        for blocks in sample_pages:
            joined = "\n\n".join(block.text for block in blocks if block.text.strip())
            sections = cls._qa_question_sections(cls._prepare_qa_page_text(joined))
            question_total += len(sections)
            if sections:
                question_pages += 1
        return question_total >= 12 or question_pages >= max(2, len(sample_pages) // 3)

    @classmethod
    def _qa_question_sections(cls, text: str) -> list[tuple[int, int, str]]:
        matches = list(QUESTION_HEADER_PATTERN.finditer(text))
        sections: list[tuple[int, int, str]] = []
        for index, match in enumerate(matches):
            question = cls._normalize_extracted_text(match.group("question"))
            if not question:
                continue
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            sections.append((start, end, question))
        return sections

    @classmethod
    def _split_nested_qa_sections(
        cls,
        *,
        section_text: str,
        fallback_question: str,
    ) -> list[tuple[str, str]]:
        prepared_section_text = cls._prepare_qa_page_text(section_text)
        nested_sections = cls._qa_question_sections(prepared_section_text)
        if len(nested_sections) <= 1:
            return [(fallback_question, section_text.strip())]

        fallback_key = cls._canonical_question_text(fallback_question)
        has_distinct_follow_up = any(
            start > 0 and cls._canonical_question_text(question) != fallback_key
            for start, _end, question in nested_sections[1:]
        )
        if not has_distinct_follow_up:
            return [(fallback_question, section_text.strip())]

        refined_sections: list[tuple[str, str]] = []
        for start, end, question in nested_sections:
            refined_section_text = prepared_section_text[start:end].strip()
            if not refined_section_text:
                continue
            refined_sections.append((question, refined_section_text))

        return refined_sections or [(fallback_question, section_text.strip())]

    @staticmethod
    def _canonical_question_text(question: str) -> str:
        return re.sub(r"\W+", " ", question).strip().lower()

    @classmethod
    def _should_skip_qa_page(
        cls,
        text: str,
        *,
        page_number: int,
        question_sections: list[tuple[int, int, str]],
    ) -> bool:
        normalized = text.lower()
        if not text.strip():
            return True
        if page_number <= 2 and any(pattern in normalized for pattern in LOW_SIGNAL_QA_PATTERNS):
            return True
        if "contents" in normalized and len(question_sections) >= 3:
            return True
        question_character_count = sum(end - start for start, end, _ in question_sections)
        non_question_character_count = max(len(text) - question_character_count, 0)
        if len(question_sections) >= 8 and non_question_character_count < 220:
            return True
        return False

    @classmethod
    def _should_carryover_question(
        cls,
        *,
        question: str,
        section_text: str,
        page_text: str,
        section_end: int,
    ) -> bool:
        answer_text = section_text.removeprefix(question).strip()
        if len(answer_text) < 220:
            return True
        return section_end >= int(len(page_text) * 0.72)

    @staticmethod
    def _question_context_chunk(*, question: str, body: str) -> str:
        cleaned_body = body.strip()
        if not cleaned_body:
            return f"Question: {question}"
        return f"Question: {question}\n\nAnswer: {cleaned_body}"

    @classmethod
    def _is_low_signal_fragment(cls, text: str) -> bool:
        normalized = text.lower()
        return any(pattern in normalized for pattern in LOW_SIGNAL_QA_PATTERNS)

    @classmethod
    def _prepare_qa_page_text(cls, text: str) -> str:
        cleaned_text = QA_NOISE_LINE_PATTERN.sub("", text)
        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
        return EMBEDDED_QUESTION_MARKER_PATTERN.sub(r"\n\1 ", cleaned_text)

    @staticmethod
    def _normalize_extracted_text(
        text: str,
        *,
        preserve_newlines: bool = False,
    ) -> str:
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
