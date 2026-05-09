from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
import unicodedata
from uuid import uuid4

from app.core.chroma_store import ChromaStore
from app.services.document_service import DocumentService, RetrievalChunkCatalogEntry
from app.services.docling_parser import DoclingDocumentParser, ParsedBlock
from app.services.keyword_service import KeywordService
from app.services.ollama_client import OllamaClient
from app.services.text_splitter import SemanticTextSplitter
from app.services.topic_index_service import TopicIndexService


logger = logging.getLogger(__name__)
DEFAULT_EMBED_BATCH_SIZE = 96
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


@dataclass
class IngestionResult:
    document_id: str
    pdf_name: str
    page_count: int
    chunk_count: int


@dataclass(frozen=True)
class PageChunkDraft:
    text: str
    metadata: dict[str, object]


class IngestionService:
    def __init__(
        self,
        *,
        document_service: DocumentService,
        keyword_service: KeywordService,
        ollama_client: OllamaClient,
        text_splitter: SemanticTextSplitter,
        chroma_store: ChromaStore,
        topic_index_service: TopicIndexService,
        document_parser: DoclingDocumentParser,
        collection_name: str = "all_chunks",
    ) -> None:
        self._document_service = document_service
        self._keyword_service = keyword_service
        self._ollama_client = ollama_client
        self._text_splitter = text_splitter
        self._chroma_store = chroma_store
        self._topic_index_service = topic_index_service
        self._document_parser = document_parser
        self._collection_name = collection_name
        self._embed_batch_size = max(
            1,
            min(
                DEFAULT_EMBED_BATCH_SIZE,
                self._chroma_store.max_batch_size or DEFAULT_EMBED_BATCH_SIZE,
            ),
        )

    def _collection(self) -> object:
        return self._chroma_store.collection(self._collection_name)

    async def ingest_pdf(
        self,
        pdf_path: Path,
        *,
        document_id: str | None = None,
        pdf_name: str | None = None,
        user_id: str,
    ) -> IngestionResult:
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        resolved_pdf_name = pdf_name or pdf_path.name
        if document_id is None:
            document_id = str(uuid4())
            self._document_service.create_pending_document(
                document_id=document_id,
                pdf_name=resolved_pdf_name,
                source_path=pdf_path,
                user_id=user_id,
            )
        else:
            existing = self._document_service.get_document_by_id(document_id, user_id=user_id)
            if existing and existing.get("pdf_name"):
                resolved_pdf_name = str(existing["pdf_name"])

        self._document_service.update_document_progress(
            document_id,
            user_id=user_id,
            status="parsing",
            progress=12,
        )

        try:
            parsed_document = await asyncio.to_thread(self._document_parser.parse, pdf_path)
            page_texts = [page.text for page in parsed_document.pages]
            page_blocks = [page.blocks for page in parsed_document.pages]
            chunking_threshold = None
            self._document_service.update_document_progress(
                document_id,
                user_id=user_id,
                status="chunking",
                progress=34,
                page_count=len(page_texts),
                chunking_threshold=chunking_threshold,
            )

            pending_chunk_ids: list[str] = []
            pending_chunk_texts: list[str] = []
            pending_chunk_metadatas: list[dict[str, object]] = []
            total_chunk_count = 0
            self._document_service.clear_document_content(document_id, user_id=user_id)
            qa_document = self._is_question_answer_document(page_blocks)
            carryover_question: str | None = None

            for page_number, (page_text, page_blocks_for_page) in enumerate(
                zip(page_texts, page_blocks, strict=False),
                start=1,
            ):
                page_chunk_drafts, carryover_question = await self._build_page_chunk_drafts(
                    page_number=page_number,
                    page_text=page_text,
                    page_blocks=page_blocks_for_page,
                    threshold=chunking_threshold,
                    qa_document=qa_document,
                    carryover_question=carryover_question,
                )
                page_chunks = [draft.text for draft in page_chunk_drafts]
                page_chunk_spans = self._chunk_spans_for_page(page_text, page_chunks)
                page_block_spans = self._block_spans_for_page(page_text, page_blocks_for_page)

                for chunk_index, draft in enumerate(page_chunk_drafts):
                    chunk_text = draft.text
                    chunk_start, chunk_end = page_chunk_spans[chunk_index]
                    source_metadata = self._source_metadata_for_chunk(
                        parser_name=parsed_document.parser_name,
                        page_text=page_text,
                        page_blocks=page_blocks_for_page,
                        page_block_spans=page_block_spans,
                        chunk_start=chunk_start,
                        chunk_end=chunk_end,
                    )
                    chunk_id = f"{document_id}:{page_number}:{chunk_index}"
                    pending_chunk_ids.append(chunk_id)
                    pending_chunk_texts.append(chunk_text)
                    chunk_metadata: dict[str, object] = {
                        "document_id": document_id,
                        "pdf_name": resolved_pdf_name,
                        "user_id": user_id,
                        "is_indexed": 0,
                        "page_number": page_number,
                        "chunk_index": chunk_index,
                        "keywords": json.dumps([]),
                        "chunking_threshold": chunking_threshold,
                    }
                    chunk_metadata.update(source_metadata)
                    chunk_metadata.update(draft.metadata)
                    if chunk_start is not None and chunk_end is not None:
                        chunk_metadata["char_start"] = chunk_start
                        chunk_metadata["char_end"] = chunk_end
                    pending_chunk_metadatas.append(chunk_metadata)
                    total_chunk_count += 1

                self._document_service.update_document_progress(
                    document_id,
                    user_id=user_id,
                    status="chunking",
                    progress=34 + int((page_number / max(len(page_texts), 1)) * 22),
                    page_count=len(page_texts),
                    chunk_count=total_chunk_count,
                    chunking_threshold=chunking_threshold,
                )

                if len(pending_chunk_texts) >= self._embed_batch_size:
                    await self._flush_chunk_batch(
                        chunk_ids=pending_chunk_ids,
                        chunk_texts=pending_chunk_texts,
                        chunk_metadatas=pending_chunk_metadatas,
                    )
                    self._document_service.update_document_progress(
                        document_id,
                        user_id=user_id,
                        status="embedding",
                        progress=62 + int((page_number / max(len(page_texts), 1)) * 10),
                        page_count=len(page_texts),
                        chunk_count=total_chunk_count,
                        chunking_threshold=chunking_threshold,
                    )

            if total_chunk_count == 0:
                raise ValueError("No text content could be extracted from the PDF.")

            self._document_service.update_document_progress(
                document_id,
                user_id=user_id,
                status="embedding",
                progress=62,
                page_count=len(page_texts),
                chunk_count=total_chunk_count,
            )

            if pending_chunk_texts:
                await self._flush_chunk_batch(
                    chunk_ids=pending_chunk_ids,
                    chunk_texts=pending_chunk_texts,
                    chunk_metadatas=pending_chunk_metadatas,
                )

            self._document_service.update_document_progress(
                document_id,
                user_id=user_id,
                status="clustering",
                progress=84,
                page_count=len(page_texts),
                chunk_count=total_chunk_count,
            )

            self._document_service.store_document(
                document_id=document_id,
                user_id=user_id,
                pdf_name=resolved_pdf_name,
                source_path=pdf_path,
                page_texts=page_texts,
                chunk_count=total_chunk_count,
                chunking_threshold=chunking_threshold,
            )
            self._document_service.publish_document_chunks(
                document_id,
                user_id=user_id,
            )
            self._document_service.update_document_progress(
                document_id,
                user_id=user_id,
                status="clustering",
                progress=94,
                page_count=len(page_texts),
                chunk_count=total_chunk_count,
            )

            return IngestionResult(
                document_id=document_id,
                pdf_name=resolved_pdf_name,
                page_count=len(page_texts),
                chunk_count=total_chunk_count,
            )
        except Exception as error:
            self._document_service.clear_document_content(document_id, user_id=user_id)
            self._document_service.mark_document_error(document_id, str(error), user_id=user_id)
            raise

    async def _flush_chunk_batch(
        self,
        *,
        chunk_ids: list[str],
        chunk_texts: list[str],
        chunk_metadatas: list[dict[str, object]],
    ) -> None:
        embeddings = await self._ollama_client.embed_texts(chunk_texts)
        self._collection().upsert(
            ids=list(chunk_ids),
            documents=list(chunk_texts),
            metadatas=list(chunk_metadatas),
            embeddings=embeddings,
        )
        self._document_service.upsert_chunk_catalog_entries(
            [
                RetrievalChunkCatalogEntry(
                    chunk_id=str(chunk_id),
                    document_id=str(metadata["document_id"]),
                    user_id=str(metadata["user_id"]),
                    pdf_name=str(metadata["pdf_name"]),
                    page_number=int(metadata["page_number"]),
                    chunk_index=int(metadata["chunk_index"]),
                    collection_id=(
                        str(metadata["collection_id"])
                        if metadata.get("collection_id") is not None
                        else None
                    ),
                    is_indexed=bool(metadata.get("is_indexed", 0)),
                    text=str(chunk_text),
                )
                for chunk_id, chunk_text, metadata in zip(
                    chunk_ids,
                    chunk_texts,
                    chunk_metadatas,
                    strict=False,
                )
            ]
        )
        chunk_ids.clear()
        chunk_texts.clear()
        chunk_metadatas.clear()

    @classmethod
    def _source_metadata_for_chunk(
        cls,
        *,
        parser_name: str,
        page_text: str,
        page_blocks: list[ParsedBlock],
        page_block_spans: list[tuple[int | None, int | None]],
        chunk_start: int | None,
        chunk_end: int | None,
    ) -> dict[str, object]:
        source_blocks = cls._source_blocks_for_chunk(
            page_blocks=page_blocks,
            page_block_spans=page_block_spans,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
        )
        if not source_blocks:
            source_blocks = [block for block in page_blocks if block.text.strip()]

        content_labels = sorted({block.label for block in source_blocks if block.label})
        source_text = cls._source_text_for_chunk(
            page_text=page_text,
            source_blocks=source_blocks,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
        )
        source_refs = sorted(
            {
                str(block.source_ref)
                for block in source_blocks
                if block.source_ref is not None and str(block.source_ref).strip()
            }
        )
        source_payload = [
            {
                "label": block.label,
                "page": block.page_number,
                "bbox": block.bbox,
                "source_ref": block.source_ref,
            }
            for block in source_blocks
        ]

        page_numbers = [block.page_number for block in source_blocks] or [1]
        return {
            "parser": parser_name,
            "content_labels": json.dumps(content_labels),
            "page_start": min(page_numbers),
            "page_end": max(page_numbers),
            "has_table": 1 if "table" in content_labels else 0,
            "source_text": source_text,
            "source_refs": json.dumps(source_refs),
            "source_blocks": json.dumps(source_payload),
        }

    @staticmethod
    def _source_text_for_chunk(
        *,
        page_text: str,
        source_blocks: list[ParsedBlock],
        chunk_start: int | None,
        chunk_end: int | None,
    ) -> str:
        if chunk_start is not None and chunk_end is not None:
            return page_text[chunk_start:chunk_end]
        return "\n\n".join(block.text for block in source_blocks if block.text.strip())

    @staticmethod
    def _source_blocks_for_chunk(
        *,
        page_blocks: list[ParsedBlock],
        page_block_spans: list[tuple[int | None, int | None]],
        chunk_start: int | None,
        chunk_end: int | None,
    ) -> list[ParsedBlock]:
        if chunk_start is None or chunk_end is None:
            return []

        selected: list[ParsedBlock] = []
        for block, (block_start, block_end) in zip(page_blocks, page_block_spans, strict=False):
            if block_start is None or block_end is None:
                continue
            if block_end <= chunk_start or block_start >= chunk_end:
                continue
            selected.append(block)
        return selected

    @staticmethod
    def _block_spans_for_page(
        page_text: str,
        page_blocks: list[ParsedBlock],
    ) -> list[tuple[int | None, int | None]]:
        spans: list[tuple[int | None, int | None]] = []
        search_start = 0
        for block in page_blocks:
            start = page_text.find(block.text, search_start)
            if start < 0:
                spans.append((None, None))
                continue
            end = start + len(block.text)
            spans.append((start, end))
            search_start = end
        return spans

    async def _build_page_chunk_drafts(
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
    def _is_question_answer_document(cls, page_blocks_by_page: list[list[ParsedBlock]]) -> bool:
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

    async def postprocess_document(
        self,
        *,
        document_id: str,
        user_id: str,
    ) -> None:
        stored = self._document_service.get_document_by_id(document_id, user_id=user_id)
        if not stored:
            return

        rows = self._collection().get(
            where={"$and": [{"document_id": document_id}, {"user_id": user_id}]},
            include=["documents", "metadatas"],
        )
        chunk_ids = [str(chunk_id) for chunk_id in rows.get("ids", [])]
        chunk_texts = [str(text) for text in rows.get("documents", [])]
        chunk_metadatas = [dict(metadata or {}) for metadata in rows.get("metadatas", [])]

        if not chunk_ids or not chunk_texts:
            self._document_service.update_document_progress(
                document_id,
                user_id=user_id,
                status="finalizing",
                progress=98,
                page_count=int(stored["page_count"]),
                chunk_count=int(stored["chunk_count"]),
            )
            return

        self._document_service.update_document_progress(
            document_id,
            user_id=user_id,
            status="clustering",
            progress=96,
            page_count=int(stored["page_count"]),
            chunk_count=int(stored["chunk_count"]),
        )

        try:
            keyword_lists = await self._keyword_service.extract_keywords(chunk_texts)
        except Exception:
            logger.exception(
                "Keyword enrichment failed for document %s. Proceeding with empty keyword metadata.",
                document_id,
            )
            keyword_lists = [[] for _ in chunk_texts]

        keyword_enriched_metadatas = [
            {
                **metadata,
                "keywords": json.dumps(keywords),
            }
            for metadata, keywords in zip(chunk_metadatas, keyword_lists, strict=False)
        ]
        if keyword_enriched_metadatas:
            self._collection().update(ids=chunk_ids, metadatas=keyword_enriched_metadatas)

        self._document_service.update_document_progress(
            document_id,
            user_id=user_id,
            status="clustering",
            progress=97,
            page_count=int(stored["page_count"]),
            chunk_count=int(stored["chunk_count"]),
        )

        try:
            semantic_groups = self._topic_index_service.semantic_groups_for_document(
                document_id=document_id,
                user_id=user_id,
            )
        except Exception:
            logger.exception(
                "Semantic grouping failed for document %s. Proceeding without semantic group metadata.",
                document_id,
            )
            semantic_groups = {}

        final_metadatas = [
            {
                **metadata,
                **semantic_groups.get(chunk_id, {}),
            }
            for chunk_id, metadata in zip(
                chunk_ids,
                keyword_enriched_metadatas,
                strict=False,
            )
        ]
        if final_metadatas:
            self._collection().update(ids=chunk_ids, metadatas=final_metadatas)

        self._document_service.update_document_progress(
            document_id,
            user_id=user_id,
            status="finalizing",
            progress=98,
            page_count=int(stored["page_count"]),
            chunk_count=int(stored["chunk_count"]),
        )

    @staticmethod
    def _chunk_spans_for_page(
        page_text: str,
        page_chunks: list[str],
    ) -> list[tuple[int | None, int | None]]:
        spans: list[tuple[int | None, int | None]] = []
        search_start = 0

        for chunk_text in page_chunks:
            exact_start = page_text.find(chunk_text, search_start)
            if exact_start >= 0:
                exact_end = exact_start + len(chunk_text)
                spans.append((exact_start, exact_end))
                search_start = exact_end
                continue

            normalized_chunk = " ".join(chunk_text.split())
            if not normalized_chunk:
                spans.append((None, None))
                continue

            whitespace_flexible_pattern = r"\s+".join(
                re.escape(part)
                for part in normalized_chunk.split()
            )
            match = re.search(whitespace_flexible_pattern, page_text[search_start:])
            if match is None:
                spans.append((None, None))
                continue

            exact_start = search_start + match.start()
            exact_end = search_start + match.end()
            spans.append((exact_start, exact_end))
            search_start = exact_end

        return spans
