from __future__ import annotations

import re

SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
PARAGRAPH_BOUNDARY_PATTERN = re.compile(r"\n{2,}")
WHITESPACE_PATTERN = re.compile(r"\s+")


class SemanticTextSplitter:
    def __init__(
        self,
        *,
        chunk_size: int,
        chunk_overlap: int,
        threshold: float = 0.75,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = max(0, min(chunk_overlap, max(chunk_size // 3, 1)))
        self._threshold = threshold

    async def split_text(
        self,
        text: str,
        *,
        threshold: float | None = None,  # noqa: ARG002
        blocks: list[str] | None = None,
    ) -> list[str]:
        normalized = text.strip()
        if not normalized:
            return []

        segments = self._normalize_segments(blocks) if blocks else self._normalize_segments_from_text(normalized)
        if not segments:
            return self._fallback_chunks(normalized)
        return self._chunk_segments(segments)

    async def auto_tune_threshold(self, page_texts: list[str]) -> float:  # noqa: ARG002
        return self._threshold

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        return [segment.strip() for segment in SENTENCE_BOUNDARY_PATTERN.split(text) if segment.strip()]

    def _chunk_segments(self, segments: list[str]) -> list[str]:
        chunks: list[str] = []
        current = ""

        for segment in segments:
            for piece in self._split_oversized_segment(segment):
                candidate = piece if not current else f"{current}\n\n{piece}"
                if not current:
                    current = piece
                    continue
                if len(candidate) <= self._chunk_size:
                    current = candidate
                    continue
                chunks.append(current)
                current = self._with_overlap(previous=current, next_piece=piece)

        if current:
            chunks.append(current)

        return [chunk for chunk in chunks if chunk.strip()]

    def _normalize_segments(self, blocks: list[str] | None) -> list[str]:
        if not blocks:
            return []
        return [
            WHITESPACE_PATTERN.sub(" ", block).strip()
            for block in blocks
            if WHITESPACE_PATTERN.sub(" ", block).strip()
        ]

    def _normalize_segments_from_text(self, text: str) -> list[str]:
        paragraphs = [
            WHITESPACE_PATTERN.sub(" ", paragraph).strip()
            for paragraph in PARAGRAPH_BOUNDARY_PATTERN.split(text)
            if WHITESPACE_PATTERN.sub(" ", paragraph).strip()
        ]
        if paragraphs:
            return paragraphs
        return self._split_sentences(text)

    def _split_oversized_segment(self, segment: str) -> list[str]:
        normalized = segment.strip()
        if len(normalized) <= self._chunk_size:
            return [normalized]

        sentences = self._split_sentences(normalized)
        if len(sentences) > 1:
            sentence_chunks = self._chunk_segments(sentences)
            if sentence_chunks:
                return sentence_chunks

        return self._fallback_chunks(normalized)

    def _fallback_chunks(self, text: str) -> list[str]:
        if len(text) <= self._chunk_size:
            return [text]

        words = text.split()
        chunks: list[str] = []
        current_words: list[str] = []

        for word in words:
            if len(word) > self._chunk_size:
                if current_words:
                    chunks.append(" ".join(current_words).strip())
                    current_words = []

                start = 0
                while start < len(word):
                    segment = word[start : start + self._chunk_size]
                    if len(segment) == self._chunk_size:
                        chunks.append(segment.strip())
                    elif segment:
                        current_words = [segment]
                    start += self._chunk_size
                continue

            candidate = " ".join([*current_words, word]).strip()
            if current_words and len(candidate) > self._chunk_size:
                chunks.append(" ".join(current_words).strip())
                overlap_words = self._tail_overlap(" ".join(current_words))
                current_words = overlap_words.split() if overlap_words else []
                current_words.append(word)
                continue
            current_words.append(word)

        if current_words:
            chunks.append(" ".join(current_words).strip())

        return [chunk for chunk in chunks if chunk]

    def _with_overlap(self, *, previous: str, next_piece: str) -> str:
        overlap = self._tail_overlap(previous)
        if not overlap:
            return next_piece
        candidate = f"{overlap}\n\n{next_piece}".strip()
        if len(candidate) <= self._chunk_size:
            return candidate
        return next_piece

    def _tail_overlap(self, text: str) -> str:
        if self._chunk_overlap <= 0:
            return ""

        normalized = text.strip()
        if not normalized:
            return ""

        sentences = self._split_sentences(normalized)
        if len(sentences) > 1:
            selected: list[str] = []
            total_length = 0
            for sentence in reversed(sentences):
                separator_length = 1 if selected else 0
                projected_length = total_length + len(sentence) + separator_length
                if selected and projected_length > self._chunk_overlap:
                    break
                selected.insert(0, sentence)
                total_length = projected_length
            overlap = " ".join(selected).strip()
            if overlap:
                return overlap

        tail = normalized[-self._chunk_overlap :].strip()
        first_space = tail.find(" ")
        if first_space > 0:
            tail = tail[first_space + 1 :]
        return tail.strip()
