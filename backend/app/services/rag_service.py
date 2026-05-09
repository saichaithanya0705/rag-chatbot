from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Sequence

import httpx

from app.core.chroma_store import ChromaStore
from app.models.schemas import CitationPayload, ToolCallPayload
from app.services.conversation_context import looks_context_dependent
from app.services.document_service import DocumentService
from app.services.kg_manager import KgManager
from app.services.message_intent import classify_message_intent
from app.services.ollama_client import OllamaClient, OllamaGenerationResult
from app.services.query_rewrite_service import QueryRewriteService
from app.services.reranker_service import RerankerService
from app.services.web_search_service import WebSearchError, WebSearchOfflineError, WebSearchResult, WebSearchService


PDF_CITATION_PATTERN = re.compile(r"\[SourceID:\s*(?P<id>[^\]]+)\]", re.IGNORECASE)
LEGACY_PDF_CITATION_PATTERN = re.compile(
    r"\[Source:\s*(?P<pdf>.+?),\s*p\.(?P<page>\d+)(?:,\s*c\.(?P<chunk>\d+))?\]",
    re.IGNORECASE,
)
WEB_CITATION_PATTERN = re.compile(r"\[Web:\s*(?P<url>https?://[^\]]+)\]", re.IGNORECASE)
THINK_BLOCK_PATTERN = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
OPEN_THINK_BLOCK_PATTERN = re.compile(r"<think\b[^>]*>.*$", re.IGNORECASE | re.DOTALL)
MODEL_THINKING_SENSITIVE_LINE_PATTERN = re.compile(
    r"(?im)^[^\n]*(?:internal|hidden|system|developer)\s+prompt[^\n]*(?:\n|$)"
    r"|^[^\n]*(?:chain[-\s]*of[-\s]*thought|internal policy|policy text)[^\n]*(?:\n|$)"
)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
RRF_K = 60
INTERACTIVE_RETRIEVAL_EMBED_TIMEOUT_SECONDS = 20.0
INTERACTIVE_THINKING_GENERATE_TIMEOUT_SECONDS = 15.0
INTERACTIVE_GENERATE_TIMEOUT_SECONDS = 45.0
MODEL_THINKING_SUMMARY_TIMEOUT_SECONDS = 18.0
PROMPT_HISTORY_USER_MESSAGE_LIMIT = 2
PROMPT_PDF_CONTEXT_LIMIT = 3
PROMPT_WEB_CONTEXT_LIMIT = 2
PROMPT_PDF_CONTEXT_CHAR_LIMIT = 600
PROMPT_WEB_CONTEXT_CHAR_LIMIT = 650
MIN_TOPIC_RETRIEVAL_CANDIDATES = 5
DIRECT_QA_MATCH_THRESHOLD = 0.7
DIRECT_QA_MIN_TOKEN_COUNT = 4
CONTEXT_FALLBACK_CHAR_LIMIT = 420
MIN_INTERACTIVE_RERANK_CANDIDATES = 6
MAX_INTERACTIVE_RERANK_CANDIDATES = 8
DOMINANT_RESULT_SHARE = 0.75
FUSED_SCORE_DOMINANCE_MARGIN = 0.01
MODEL_THINKING_SEGMENT_CHAR_LIMIT = 2400
PREVIEW_NOISE_LINE_PATTERN = re.compile(r"(?im)^\s*(?:page\s+\d+\b.*|[^\n\r]*copyright\b.*)$")
ONE_SENTENCE_PATTERN = re.compile(r"\b(?:one|1)\s+(?:short\s+)?sentence\b", re.IGNORECASE)
TWO_SENTENCE_PATTERN = re.compile(r"\b(?:two|2)\s+(?:short\s+)?sentences\b", re.IGNORECASE)
THREE_SENTENCE_PATTERN = re.compile(r"\b(?:three|3)\s+(?:short\s+)?sentences\b", re.IGNORECASE)
CONCISE_ANSWER_PATTERN = re.compile(
    r"\b(?:brief(?:ly)?|concise(?:ly)?|short(?:er)?|summari[sz]e|summary|in brief|quick(?:ly)?)\b",
    re.IGNORECASE,
)
LOW_SIGNAL_ANSWER_PREFIX_PATTERN = re.compile(
    r"^(?:in the above|in the below|the above|the below|but\b|and the|getinstance\b)",
    re.IGNORECASE,
)
COMPARISON_QUERY_PATTERN = re.compile(
    r"\b(compare|comparison|contrast|difference(?:s)?|differentiate|vs\.?|versus)\b",
    re.IGNORECASE,
)
BETWEEN_COMPARISON_PATTERN = re.compile(
    r"\bbetween\s+(?P<left>.+?)\s+\band\b\s+(?P<right>.+)$",
    re.IGNORECASE,
)
COMPARISON_SPLIT_PATTERN = re.compile(r"\b(?:and|vs\.?|versus)\b", re.IGNORECASE)
DIRECT_QA_PATTERN = re.compile(
    r"^\s*(?:question:\s*(?P<question>.+?)\n+\s*answer:\s*(?P<answer>.+)|(?P<numbered_question>\d{1,3}[.)]\s*.+?)\n+\n*(?P<numbered_answer>.+))$",
    re.IGNORECASE | re.DOTALL,
)
COMPARISON_GENERIC_TOKENS = frozenset(
    {
        "java",
        "class",
        "classes",
        "object",
        "objects",
        "type",
        "types",
    }
)
LOGGER = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: str
    collection_id: str
    document_id: str
    pdf_name: str
    page_number: int
    chunk_index: int
    text: str


@dataclass
class CandidateChunk:
    chunk_id: str
    collection_id: str
    document_id: str
    pdf_name: str
    page_number: int
    chunk_index: int
    text: str
    fused_score: float = 0.0
    rerank_score: float | None = None


@dataclass(frozen=True)
class RetrievedContext:
    id: str
    kind: str
    label: str
    text: str
    excerpt: str
    document_id: str | None = None
    pdf_name: str | None = None
    page_number: int | None = None
    chunk_index: int | None = None
    url: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]
    top_rerank_score: float | None


@dataclass
class PreparedAnswer:
    question: str
    prompt: str
    system_prompt: str
    contexts: list[RetrievedContext]
    shortcut_answer: str | None = None
    shortcut_citations: list[CitationPayload] = field(default_factory=list)
    tool_call: ToolCallPayload | None = None
    web_search_used: bool = False
    offline_warning: str | None = None
    cross_session_turn_count: int = 0
    response_mode: str = "grounded"
    trace_detail: str | None = None
    reasoning_segments: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FinalizedAnswer:
    answer: str
    citations: list[CitationPayload]
    model_thinking: str | None = None
    generation_warning: str | None = None


class RagService:
    def __init__(
        self,
        *,
        ollama_client: OllamaClient,
        chroma_store: ChromaStore,
        document_service: DocumentService,
        kg_manager: KgManager,
        query_rewrite_service: QueryRewriteService,
        reranker_service: RerankerService,
        web_search_service: WebSearchService,
        collection_name: str = "all_chunks",
        top_k: int,
        web_search_score_threshold: float,
    ) -> None:
        self._ollama_client = ollama_client
        self._chroma_store = chroma_store
        self._document_service = document_service
        self._kg_manager = kg_manager
        self._query_rewrite_service = query_rewrite_service
        self._reranker_service = reranker_service
        self._web_search_service = web_search_service
        self._collection_name = collection_name
        self._top_k = top_k
        self._web_search_score_threshold = web_search_score_threshold

    async def answer_question(
        self,
        question: str,
        *,
        collection_id: str = "all-pdfs",
        history_messages: Sequence[dict[str, str]] | None = None,
        cross_session_turn_count: int = 0,
        web_search_enabled: bool = True,
        thinking_enabled: bool = False,
        user_id: str,
    ) -> tuple[
        str,
        list[CitationPayload],
        ToolCallPayload | None,
        bool,
        str | None,
        int,
        str | None,
        str | None,
        str,
        str | None,
    ]:
        prepared = await self.prepare_answer(
            question,
            collection_id=collection_id,
            history_messages=history_messages,
            cross_session_turn_count=cross_session_turn_count,
            web_search_enabled=web_search_enabled,
            thinking_enabled=thinking_enabled,
            user_id=user_id,
        )
        if prepared.shortcut_answer is not None:
            model_thinking = await self.summarize_model_thinking(
                prepared.reasoning_segments,
                question=prepared.question,
                answer=prepared.shortcut_answer,
                contexts=prepared.contexts,
            ) if thinking_enabled else None
            return (
                prepared.shortcut_answer,
                prepared.shortcut_citations,
                prepared.tool_call,
                prepared.web_search_used,
                prepared.offline_warning,
                prepared.cross_session_turn_count,
                model_thinking,
                None,
                prepared.response_mode,
                prepared.trace_detail,
            )

        finalized = await self.generate_finalized_answer(
            prepared,
            thinking_enabled=thinking_enabled,
        )
        return (
            finalized.answer,
            finalized.citations,
            prepared.tool_call,
            prepared.web_search_used,
            prepared.offline_warning,
            prepared.cross_session_turn_count,
            finalized.model_thinking,
            finalized.generation_warning,
            prepared.response_mode,
            prepared.trace_detail,
        )

    async def generate_finalized_answer(
        self,
        prepared: PreparedAnswer,
        *,
        thinking_enabled: bool,
    ) -> FinalizedAnswer:
        attempt_order = [thinking_enabled]
        if thinking_enabled:
            attempt_order.append(False)

        last_result: FinalizedAnswer | None = None
        last_error: Exception | None = None

        for attempt_index, include_thinking in enumerate(attempt_order):
            attempt_started_at = asyncio.get_running_loop().time()
            LOGGER.info(
                "Answer generation attempt %s started (thinking=%s).",
                attempt_index + 1,
                include_thinking,
            )
            try:
                raw_answer = await self._ollama_client.generate_answer(
                    prompt=prepared.prompt,
                    system_prompt=prepared.system_prompt,
                    options=self._interactive_generation_options(
                        question=prepared.question,
                        contexts=prepared.contexts,
                    ),
                    include_thinking=include_thinking,
                    timeout=(
                        INTERACTIVE_THINKING_GENERATE_TIMEOUT_SECONDS
                        if include_thinking
                        else INTERACTIVE_GENERATE_TIMEOUT_SECONDS
                    ),
                )
            except Exception as error:  # noqa: BLE001
                last_error = error
                if include_thinking and attempt_index < len(attempt_order) - 1:
                    LOGGER.warning(
                        "Reasoning-enabled answer generation failed; retrying without thinking mode.",
                        exc_info=True,
                    )
                    continue
                if self._is_interactive_timeout(error):
                    LOGGER.warning(
                        "Interactive answer generation exceeded the time budget; falling back to retrieved evidence.",
                        exc_info=True,
                    )
                    return self._fallback_finalized_answer(
                        prepared.contexts,
                        generation_warning=(
                            "The model exceeded the interactive time budget, so this answer was composed "
                            "directly from the strongest retrieved evidence."
                        ),
                    )
                raise

            finalized = self._finalize_generation_result(
                raw_answer,
                prepared.contexts,
                include_thinking=include_thinking,
            )
            if include_thinking:
                finalized = FinalizedAnswer(
                    answer=finalized.answer,
                    citations=finalized.citations,
                    model_thinking=await self.summarize_model_thinking(
                        [
                            *prepared.reasoning_segments,
                            *self._reasoning_segments_from(
                                "Answer generation",
                                raw_answer.thinking,
                            ),
                        ],
                        question=prepared.question,
                        answer=finalized.answer,
                        contexts=prepared.contexts,
                    ),
                    generation_warning=finalized.generation_warning,
                )
            LOGGER.info(
                "Answer generation attempt %s finished in %.2fs (thinking=%s).",
                attempt_index + 1,
                asyncio.get_running_loop().time() - attempt_started_at,
                include_thinking,
            )
            last_result = finalized
            if not (
                include_thinking
                and self.should_retry_without_thinking(
                    finalized.answer,
                    finalized.citations,
                    prepared.contexts,
                )
            ):
                return finalized

            LOGGER.warning(
                "Reasoning-enabled answer could not be grounded; retrying without thinking mode."
            )

        if last_result is not None:
            if prepared.contexts and last_result.answer == self._ungrounded_answer_message():
                return self._fallback_finalized_answer(
                    prepared.contexts,
                    generation_warning=(
                        "The model could not ground a confident generated answer, so this response was "
                        "composed directly from the strongest retrieved evidence."
                    ),
                )
            return last_result
        if last_error is not None:
            if prepared.contexts and self._is_interactive_timeout(last_error):
                return self._fallback_finalized_answer(
                    prepared.contexts,
                    generation_warning=(
                        "The model exceeded the interactive time budget, so this answer was composed "
                        "directly from the strongest retrieved evidence."
                    ),
                )
            raise last_error
        raise RuntimeError("Answer generation ended without a result.")

    async def prepare_answer(
        self,
        question: str,
        *,
        collection_id: str = "all-pdfs",
        history_messages: Sequence[dict[str, str]] | None = None,
        cross_session_turn_count: int = 0,
        web_search_enabled: bool = True,
        thinking_enabled: bool = False,
        user_id: str,
    ) -> PreparedAnswer:
        message_intent = await classify_message_intent(
            question,
            ollama_client=self._ollama_client,
            include_thinking=thinking_enabled,
        )
        intent_reasoning_segments = self._reasoning_segments_from(
            "Intent classification",
            message_intent.model_thinking,
        )
        if message_intent.kind == "conversation" and message_intent.reply is not None:
            return PreparedAnswer(
                question=question,
                prompt="",
                system_prompt="You answer plainly.",
                contexts=[],
                shortcut_answer=message_intent.reply,
                cross_session_turn_count=cross_session_turn_count,
                response_mode="conversation",
                trace_detail=message_intent.trace_detail,
                reasoning_segments=intent_reasoning_segments,
            )

        has_local_context = self._has_local_context(collection_id, user_id=user_id)
        if not has_local_context and not web_search_enabled:
            return PreparedAnswer(
                question=question,
                prompt="",
                system_prompt="You answer plainly.",
                contexts=[],
                shortcut_answer=self._no_context_message(
                    web_search_enabled=False,
                    offline_warning=None,
                ),
                cross_session_turn_count=cross_session_turn_count,
                reasoning_segments=intent_reasoning_segments,
            )

        retrieval_query = question
        try:
            retrieval_query = await self._query_rewrite_service.rewrite_query(
                question,
                history_messages=history_messages or [],
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning("Query rewrite failed; falling back to the raw user question.", exc_info=True)

        retrieval = RetrievalResult(chunks=[], top_rerank_score=None)
        lexical_shortcut = self._direct_lexical_shortcut(
            retrieval_query,
            collection_id=collection_id,
            user_id=user_id,
        )
        if lexical_shortcut is not None:
            shortcut_context, shortcut_answer = lexical_shortcut
            return PreparedAnswer(
                question=question,
                prompt="",
                system_prompt="You answer plainly.",
                contexts=[shortcut_context],
                shortcut_answer=shortcut_answer,
                shortcut_citations=[self._citation_from_context(shortcut_context)],
                cross_session_turn_count=cross_session_turn_count,
                reasoning_segments=intent_reasoning_segments,
            )

        comparison_contexts = self._comparison_contexts(
            retrieval_query,
            collection_id=collection_id,
            user_id=user_id,
        )
        if len(comparison_contexts) >= 2:
            comparison_shortcut = self._direct_comparison_shortcut(
                question,
                comparison_contexts,
            )
            if comparison_shortcut is not None:
                shortcut_answer, shortcut_citations = comparison_shortcut
                return PreparedAnswer(
                    question=question,
                    prompt="",
                    system_prompt="You answer plainly.",
                    contexts=comparison_contexts,
                    shortcut_answer=shortcut_answer,
                    shortcut_citations=shortcut_citations,
                    cross_session_turn_count=cross_session_turn_count,
                    reasoning_segments=intent_reasoning_segments,
                )
            prompt = self._build_prompt(
                question=question,
                contexts=comparison_contexts,
                history_messages=history_messages or [],
            )
            system_prompt = (
                "Answer only from the supplied evidence blocks. "
                "Prefer PDF evidence when it directly answers the question. "
                "Use web evidence only to fill gaps or answer current facts the PDFs do not cover. "
                "If the evidence is insufficient, say so plainly. "
                "Grounded prose matters more than repeating source markers. "
                "If you include a source marker, copy it exactly from the evidence blocks. "
                "Do not invent, repair, or paraphrase source markers."
            )
            return PreparedAnswer(
                question=question,
                prompt=prompt,
                system_prompt=system_prompt,
                contexts=comparison_contexts,
                cross_session_turn_count=cross_session_turn_count,
                reasoning_segments=intent_reasoning_segments,
            )

        if has_local_context:
            try:
                query_embedding = (
                    await self._ollama_client.embed_texts(
                        [retrieval_query],
                        timeout=INTERACTIVE_RETRIEVAL_EMBED_TIMEOUT_SECONDS,
                    )
                )[0]
            except Exception:  # noqa: BLE001
                LOGGER.warning(
                    "Local retrieval embedding failed; falling back to lexical retrieval only.",
                    exc_info=True,
                )
                retrieval = await asyncio.to_thread(
                    self._retrieve_chunks_without_embedding,
                    retrieval_query,
                    collection_id,
                    user_id=user_id,
                )
            else:
                retrieval = await asyncio.to_thread(
                    self._retrieve_chunks,
                    retrieval_query,
                    query_embedding,
                    collection_id,
                    user_id=user_id,
                )
                if not retrieval.chunks and collection_id == "all-pdfs":
                    retrieval = await asyncio.to_thread(
                        self._fallback_chunks,
                        retrieval_query,
                        query_embedding,
                        user_id=user_id,
                    )

        pdf_contexts = [self._pdf_context_from_chunk(chunk) for chunk in retrieval.chunks]
        tool_call = (
            ToolCallPayload(label="Searched the web for", query=retrieval_query)
            if web_search_enabled
            and (not pdf_contexts or self._should_use_web_search(retrieval.top_rerank_score))
            else None
        )
        web_contexts: list[RetrievedContext] = []
        web_search_used = False
        offline_warning: str | None = None

        if tool_call is not None:
            try:
                web_results = await self._web_search_service.search(retrieval_query)
                web_results = await asyncio.to_thread(
                    self._rerank_web_results,
                    retrieval_query,
                    web_results,
                )
                web_contexts = self._web_contexts_from_results(web_results)
                web_search_used = bool(web_contexts)
            except WebSearchOfflineError as error:
                offline_warning = str(error)
            except WebSearchError as error:
                offline_warning = str(error)

        contexts = self._select_contexts(pdf_contexts, web_contexts)
        if not contexts:
            return PreparedAnswer(
                question=question,
                prompt="",
                system_prompt="You answer plainly.",
                contexts=[],
                shortcut_answer=self._no_context_message(
                    web_search_enabled=web_search_enabled,
                    offline_warning=offline_warning,
                ),
                tool_call=tool_call,
                web_search_used=web_search_used,
                offline_warning=offline_warning,
                cross_session_turn_count=cross_session_turn_count,
                reasoning_segments=intent_reasoning_segments,
            )

        shortcut = self._direct_context_shortcut(question, contexts)
        if shortcut is not None:
            return PreparedAnswer(
                question=question,
                prompt="",
                system_prompt="You answer plainly.",
                contexts=contexts,
                shortcut_answer=shortcut.answer,
                shortcut_citations=shortcut.citations,
                tool_call=tool_call,
                web_search_used=web_search_used,
                offline_warning=offline_warning,
                cross_session_turn_count=cross_session_turn_count,
                reasoning_segments=intent_reasoning_segments,
            )

        prompt = self._build_prompt(
            question=question,
            contexts=contexts,
            history_messages=history_messages or [],
        )
        system_prompt = (
            "Answer only from the supplied evidence blocks. "
            "Prefer PDF evidence when it directly answers the question. "
            "Use web evidence only to fill gaps or answer current facts the PDFs do not cover. "
            "If the evidence is insufficient, say so plainly. "
            "Grounded prose matters more than repeating source markers. "
            "If you include a source marker, copy it exactly from the evidence blocks. "
            "Do not invent, repair, or paraphrase source markers."
        )
        return PreparedAnswer(
            question=question,
            prompt=prompt,
            system_prompt=system_prompt,
            contexts=contexts,
            tool_call=tool_call,
            web_search_used=web_search_used,
            offline_warning=offline_warning,
            cross_session_turn_count=cross_session_turn_count,
            reasoning_segments=intent_reasoning_segments,
        )

    def finalize_answer(
        self,
        raw_answer: str,
        contexts: list[RetrievedContext],
    ) -> tuple[str, list[CitationPayload]]:
        normalized_answer = self._strip_thinking_blocks(raw_answer.strip())
        clean_answer = self._normalize_answer_text(
            self._strip_citation_markers(normalized_answer).strip()
        )
        citations = self._extract_citations(normalized_answer, contexts)
        if not citations and contexts and clean_answer:
            citations = self._derive_citations_from_answer(clean_answer, contexts)
        if contexts and (
            not citations
            or self._references_unknown_sources(normalized_answer, contexts)
            or self._has_uncited_substantive_segments(normalized_answer, contexts)
        ):
            return self._ungrounded_answer_message(), []
        return clean_answer, citations

    def should_retry_without_thinking(
        self,
        answer: str,
        citations: list[CitationPayload],
        contexts: list[RetrievedContext],
    ) -> bool:
        return bool(contexts) and not citations and answer == self._ungrounded_answer_message()

    def _finalize_generation_result(
        self,
        raw_answer: OllamaGenerationResult,
        contexts: list[RetrievedContext],
        *,
        include_thinking: bool,
    ) -> FinalizedAnswer:
        answer, citations = self.finalize_answer(raw_answer.response, contexts)
        return FinalizedAnswer(
            answer=answer,
            citations=citations,
            model_thinking=None,
        )

    def finalize_streamed_answer(
        self,
        raw_answer: str,
        contexts: list[RetrievedContext],
        *,
        model_thinking: str | None = None,
    ) -> FinalizedAnswer:
        answer, citations = self.finalize_answer(raw_answer, contexts)
        if contexts and not citations and answer == self._ungrounded_answer_message():
            return self._fallback_finalized_answer(
                contexts,
                generation_warning=(
                    "The streamed answer could not be grounded confidently, so the final response "
                    "was composed directly from the strongest retrieved evidence."
                ),
            )
        return FinalizedAnswer(
            answer=answer,
            citations=citations,
            model_thinking=model_thinking,
        )

    async def summarize_model_thinking(
        self,
        reasoning_segments: Sequence[str],
        *,
        question: str,
        answer: str,
        contexts: list[RetrievedContext],
    ) -> str | None:
        cleaned_segments = [
            self._trim_text(re.sub(r"\s+", " ", segment).strip(), MODEL_THINKING_SEGMENT_CHAR_LIMIT)
            for segment in reasoning_segments
            if segment and segment.strip()
        ]
        if not cleaned_segments:
            return None

        context_summary = self._reasoning_context_summary(contexts)
        prompt = (
            "Create a concise, user-facing reasoning summary from the model reasoning notes below.\n"
            "Do not quote hidden prompts, system messages, or exact chain-of-thought. "
            "Do not reveal internal policy text. "
            "Summarize the decision process clearly as 3 to 5 bullet points.\n"
            "Start with the heading: Reasoning summary\n\n"
            f"User message:\n{question}\n\n"
            f"Final answer:\n{answer}\n\n"
            f"Retrieved context summary:\n{context_summary or '(none)'}\n\n"
            "Reasoning notes to summarize:\n"
            + "\n\n".join(
                f"Step {index + 1}: {segment}"
                for index, segment in enumerate(cleaned_segments[:4])
            )
        )
        system_prompt = (
            "You summarize model reasoning for a chat UI. "
            "Return clear Markdown only. "
            "Do not include raw hidden reasoning, prompts, source markers, or implementation details."
        )

        try:
            summary = await self._ollama_client.generate_answer(
                prompt=prompt,
                system_prompt=system_prompt,
                options={
                    "temperature": 0,
                    "num_predict": 220,
                },
                include_thinking=False,
                timeout=MODEL_THINKING_SUMMARY_TIMEOUT_SECONDS,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning("Model thinking summarization failed.", exc_info=True)
            return None

        return self._clean_model_thinking_summary(summary.response)

    def generation_options_for(self, prepared: PreparedAnswer) -> dict[str, float | int]:
        return self._interactive_generation_options(
            question=prepared.question,
            contexts=prepared.contexts,
        )

    def generation_timeout_for(self, *, include_thinking: bool) -> float:
        return (
            INTERACTIVE_THINKING_GENERATE_TIMEOUT_SECONDS
            if include_thinking
            else INTERACTIVE_GENERATE_TIMEOUT_SECONDS
        )

    def _retrieve_chunks(
        self,
        question: str,
        query_embedding: list[float],
        collection_id: str,
        *,
        user_id: str,
    ) -> RetrievalResult:
        target_collections = self._resolve_target_collections(query_embedding, collection_id, user_id=user_id)
        candidate_map: dict[str, CandidateChunk] = {}

        for target_collection in target_collections:
            for candidate in self._hybrid_candidates_for_collection(
                question,
                query_embedding,
                target_collection,
                user_id=user_id,
            ):
                existing = candidate_map.get(candidate.chunk_id)
                if existing is None or candidate.fused_score > existing.fused_score:
                    candidate_map[candidate.chunk_id] = candidate

        # Only include the global flat collection when the user is querying
        # "all-pdfs". When a specific topic collection is selected, the flat
        # collection must NOT be searched — otherwise results from unrelated
        # PDFs leak into the scoped retrieval.
        include_flat = self._should_query_flat_collection(
            collection_id=collection_id,
            target_collections=target_collections,
            candidate_count=len(candidate_map),
        )
        if include_flat:
            for candidate in self._hybrid_candidates_for_collection(
                question,
                query_embedding,
                self._collection_name,
                user_id=user_id,
            ):
                existing = candidate_map.get(candidate.chunk_id)
                if existing is None or candidate.fused_score > existing.fused_score:
                    candidate_map[candidate.chunk_id] = candidate

        scoped_collection_names = list(target_collections)
        if include_flat and self._collection_name not in scoped_collection_names:
            scoped_collection_names.append(self._collection_name)

        self._merge_comparison_lexical_candidates(
            candidate_map,
            question=question,
            collection_names=scoped_collection_names,
            user_id=user_id,
        )

        if not candidate_map:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        fused_candidates = sorted(
            candidate_map.values(),
            key=lambda chunk: chunk.fused_score,
            reverse=True,
        )
        rerank_pool_limit = self._rerank_pool_limit(
            question=question,
            ordered_candidates=fused_candidates,
        )
        fused_candidates = self._select_rerank_candidate_pool(
            question=question,
            ordered_candidates=fused_candidates,
            collection_names=scoped_collection_names,
            user_id=user_id,
            limit=rerank_pool_limit,
        )
        ranked_candidates = self._rank_candidates(
            question=question,
            ordered_candidates=fused_candidates,
        )
        selected_chunks = self._select_final_chunks(
            question=question,
            ranked_candidates=ranked_candidates,
            collection_names=scoped_collection_names,
            user_id=user_id,
        )

        return RetrievalResult(
            chunks=[
                RetrievedChunk(
                    chunk_id=candidate.chunk_id,
                    collection_id=candidate.collection_id,
                    document_id=candidate.document_id,
                    pdf_name=candidate.pdf_name,
                    page_number=candidate.page_number,
                    chunk_index=candidate.chunk_index,
                    text=candidate.text,
                )
                for candidate in selected_chunks
            ],
            top_rerank_score=selected_chunks[0].rerank_score if selected_chunks else None,
        )

    def _should_query_flat_collection(
        self,
        *,
        collection_id: str,
        target_collections: list[str],
        candidate_count: int,
    ) -> bool:
        if collection_id != "all-pdfs":
            return False
        if self._collection_name in target_collections:
            return False
        if not target_collections:
            return True
        return candidate_count < max(self._top_k, MIN_TOPIC_RETRIEVAL_CANDIDATES)

    def _retrieve_chunks_without_embedding(
        self,
        question: str,
        collection_id: str,
        *,
        user_id: str,
    ) -> RetrievalResult:
        target_collection = self._collection_name if collection_id == "all-pdfs" else collection_id
        candidates = self._lexical_candidates_for_collection(
            question,
            target_collection,
            user_id=user_id,
            limit=max(self._top_k * 4, 16),
        )
        candidate_map = {candidate.chunk_id: candidate for candidate in candidates}
        self._merge_comparison_lexical_candidates(
            candidate_map,
            question=question,
            collection_names=[target_collection],
            user_id=user_id,
        )
        candidates = sorted(
            candidate_map.values(),
            key=lambda candidate: candidate.fused_score,
            reverse=True,
        )
        rerank_pool_limit = self._rerank_pool_limit(
            question=question,
            ordered_candidates=candidates,
        )
        candidates = self._select_rerank_candidate_pool(
            question=question,
            ordered_candidates=candidates,
            collection_names=[target_collection],
            user_id=user_id,
            limit=rerank_pool_limit,
        )
        if not candidates:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        for rank, candidate in enumerate(candidates):
            candidate.fused_score = self._rrf_score(rank)

        ranked_candidates = self._rank_candidates(
            question=question,
            ordered_candidates=candidates,
        )
        selected_chunks = self._select_final_chunks(
            question=question,
            ranked_candidates=ranked_candidates,
            collection_names=[target_collection],
            user_id=user_id,
        )

        return RetrievalResult(
            chunks=[
                RetrievedChunk(
                    chunk_id=candidate.chunk_id,
                    collection_id=candidate.collection_id,
                    document_id=candidate.document_id,
                    pdf_name=candidate.pdf_name,
                    page_number=candidate.page_number,
                    chunk_index=candidate.chunk_index,
                    text=candidate.text,
                )
                for candidate in selected_chunks
            ],
            top_rerank_score=selected_chunks[0].rerank_score if selected_chunks else None,
        )

    def _resolve_target_collections(
        self,
        query_embedding: list[float],
        collection_id: str,
        *,
        user_id: str,
    ) -> list[str]:
        if collection_id != "all-pdfs":
            return [collection_id] if self._kg_manager.has_topic(user_id, collection_id) else []

        seed_topics = self._kg_manager.rank_topics(user_id, query_embedding, top_n=3)
        return self._kg_manager.expand_topics(user_id, seed_topics, limit=6, min_weight=0.4)

    def _hybrid_candidates_for_collection(
        self,
        question: str,
        query_embedding: list[float],
        collection_id: str,
        *,
        user_id: str,
    ) -> list[CandidateChunk]:
        limit = max(self._top_k * 2, 8)
        vector_candidates = {
            candidate.chunk_id: candidate
            for candidate in self._vector_candidates_for_collection(
                query_embedding,
                collection_id,
                user_id=user_id,
                limit=limit,
            )
        }

        candidates = dict(vector_candidates)
        for rank, lexical_candidate in enumerate(
            self._lexical_candidates_for_collection(
                question,
                collection_id,
                user_id=user_id,
                limit=limit,
            )
        ):
            chunk_id = lexical_candidate.chunk_id
            candidate = candidates.get(chunk_id)
            if candidate is None:
                candidate = lexical_candidate
                candidates[chunk_id] = candidate
            candidate.fused_score += self._rrf_score(rank)

        return list(candidates.values())

    def _lexical_candidates_for_collection(
        self,
        question: str,
        collection_id: str,
        *,
        user_id: str,
        limit: int,
    ) -> list[CandidateChunk]:
        fts_query = self._build_fts_query(question)
        if not fts_query:
            return []

        rows = self._document_service.search_chunk_catalog(
            query=fts_query,
            collection_id=collection_id,
            user_id=user_id,
            limit=limit,
        )
        return [
            CandidateChunk(
                chunk_id=row.chunk_id,
                collection_id=row.collection_id or collection_id,
                document_id=row.document_id,
                pdf_name=row.pdf_name,
                page_number=row.page_number,
                chunk_index=row.chunk_index,
                text=row.text,
            )
            for row in rows
        ]

    def _merge_comparison_lexical_candidates(
        self,
        candidate_map: dict[str, CandidateChunk],
        *,
        question: str,
        collection_names: Sequence[str],
        user_id: str,
    ) -> None:
        subqueries = self._comparison_subqueries(question)
        if not subqueries:
            return

        unique_collections = list(dict.fromkeys(collection_names))
        for subquery in subqueries:
            for collection_name in unique_collections:
                for rank, candidate in enumerate(
                    self._lexical_candidates_for_collection(
                        subquery,
                        collection_name,
                        user_id=user_id,
                        limit=max(self._top_k, 4),
                    )
                ):
                    bonus = self._rrf_score(rank) * 0.75
                    existing = candidate_map.get(candidate.chunk_id)
                    if existing is None:
                        candidate.fused_score = bonus
                        candidate_map[candidate.chunk_id] = candidate
                    else:
                        existing.fused_score += bonus

    def _select_final_chunks(
        self,
        *,
        question: str,
        ranked_candidates: Sequence[CandidateChunk],
        collection_names: Sequence[str],
        user_id: str,
    ) -> list[CandidateChunk]:
        coverage_groups = self._comparison_hit_groups(
            question=question,
            collection_names=collection_names,
            user_id=user_id,
        )
        if not coverage_groups:
            return list(ranked_candidates[: self._top_k])

        selected: list[CandidateChunk] = []
        selected_ids: set[str] = set()
        for hit_ids in coverage_groups:
            for candidate in ranked_candidates:
                if candidate.chunk_id not in hit_ids or candidate.chunk_id in selected_ids:
                    continue
                selected.append(candidate)
                selected_ids.add(candidate.chunk_id)
                break

        for candidate in ranked_candidates:
            if candidate.chunk_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.chunk_id)
            if len(selected) >= self._top_k:
                break

        return selected[: self._top_k]

    def _select_rerank_candidate_pool(
        self,
        *,
        question: str,
        ordered_candidates: Sequence[CandidateChunk],
        collection_names: Sequence[str],
        user_id: str,
        limit: int,
    ) -> list[CandidateChunk]:
        if not ordered_candidates:
            return []

        selected = list(ordered_candidates[:limit])
        selected_ids = {candidate.chunk_id for candidate in selected}
        for hit_ids in self._comparison_hit_groups(
            question=question,
            collection_names=collection_names,
            user_id=user_id,
        ):
            if any(candidate.chunk_id in hit_ids for candidate in selected):
                continue
            for candidate in ordered_candidates:
                if candidate.chunk_id not in hit_ids or candidate.chunk_id in selected_ids:
                    continue
                selected.append(candidate)
                selected_ids.add(candidate.chunk_id)
                break

        return selected

    def _rerank_pool_limit(
        self,
        *,
        question: str,
        ordered_candidates: Sequence[CandidateChunk],
    ) -> int:
        if not ordered_candidates:
            return 0
        if self._comparison_subqueries(question):
            return min(len(ordered_candidates), max(self._top_k * 2, MAX_INTERACTIVE_RERANK_CANDIDATES))
        return min(
            len(ordered_candidates),
            max(self._top_k + 1, MIN_INTERACTIVE_RERANK_CANDIDATES),
        )

    def _should_rerank_candidates(
        self,
        *,
        question: str,
        ordered_candidates: Sequence[CandidateChunk],
    ) -> bool:
        if len(ordered_candidates) <= 1:
            return False
        if self._comparison_subqueries(question):
            return True

        top_window = list(ordered_candidates[: max(self._top_k, 4)])
        if len(top_window) <= 1:
            return False

        fused_margin = top_window[0].fused_score - top_window[-1].fused_score
        if fused_margin >= FUSED_SCORE_DOMINANCE_MARGIN:
            return False

        dominant_document_count = Counter(candidate.document_id for candidate in top_window).most_common(1)[0][1]
        if dominant_document_count / len(top_window) >= DOMINANT_RESULT_SHARE:
            return False

        collection_counts = Counter(
            candidate.collection_id
            for candidate in top_window
            if candidate.collection_id
        )
        if collection_counts:
            dominant_collection_count = collection_counts.most_common(1)[0][1]
            if dominant_collection_count / len(top_window) >= DOMINANT_RESULT_SHARE:
                return False

        return True

    def _rank_candidates(
        self,
        *,
        question: str,
        ordered_candidates: Sequence[CandidateChunk],
    ) -> list[CandidateChunk]:
        ranked_candidates = list(ordered_candidates)
        if not ranked_candidates or not self._should_rerank_candidates(
            question=question,
            ordered_candidates=ranked_candidates,
        ):
            return ranked_candidates

        rerank_scores = self._reranker_service.score_pairs(
            question,
            [candidate.text for candidate in ranked_candidates],
        )
        for candidate, score in zip(ranked_candidates, rerank_scores, strict=False):
            candidate.rerank_score = score

        return sorted(
            ranked_candidates,
            key=lambda chunk: (
                chunk.rerank_score if chunk.rerank_score is not None else float("-inf"),
                chunk.fused_score,
            ),
            reverse=True,
        )

    def _comparison_hit_groups(
        self,
        *,
        question: str,
        collection_names: Sequence[str],
        user_id: str,
    ) -> list[set[str]]:
        subqueries = self._comparison_subqueries(question)
        if not subqueries:
            return []

        unique_collections = list(dict.fromkeys(collection_names))
        groups: list[set[str]] = []
        for subquery in subqueries:
            hit_ids: set[str] = set()
            for collection_name in unique_collections:
                hit_ids.update(
                    candidate.chunk_id
                    for candidate in self._lexical_candidates_for_collection(
                        subquery,
                        collection_name,
                        user_id=user_id,
                        limit=max(self._top_k, 4),
                    )
                )
            if hit_ids:
                groups.append(hit_ids)
        return groups

    @classmethod
    def _comparison_subqueries(cls, question: str) -> list[str]:
        normalized = " ".join(question.strip().split())
        if not normalized or not COMPARISON_QUERY_PATTERN.search(normalized):
            return []

        normalized = re.sub(
            r"\b(?:based only on|based on|using only)\b.*$",
            "",
            normalized,
            flags=re.IGNORECASE,
        ).strip()
        normalized = re.sub(
            r"\b(?:in|with)\s+(?:one|two|three|1|2|3)\s+(?:short\s+)?sentences?\b.*$",
            "",
            normalized,
            flags=re.IGNORECASE,
        ).strip()

        between_match = BETWEEN_COMPARISON_PATTERN.search(normalized)
        if between_match:
            raw_parts = [between_match.group("left"), between_match.group("right")]
        else:
            raw_parts = COMPARISON_SPLIT_PATTERN.split(normalized)

        subqueries: list[str] = []
        for part in raw_parts:
            cleaned = re.sub(
                r"^(?:compare|comparison|contrast|difference(?:s)?(?: between)?|differentiate)\s+",
                "",
                part.strip(),
                flags=re.IGNORECASE,
            )
            cleaned = cleaned.strip(" ?.,:;")
            if len(cls._tokenize(cleaned)) < 2:
                continue
            if cleaned.lower() == question.strip().lower():
                continue
            subqueries.append(cleaned)

        return list(dict.fromkeys(subqueries))

    @classmethod
    def _comparison_search_query(cls, subquery: str) -> str:
        tokens = [token for token in cls._tokenize(subquery) if len(token) > 2]
        if len(tokens) <= 1:
            return subquery.strip()

        filtered_tokens = [
            token
            for token in tokens
            if token not in COMPARISON_GENERIC_TOKENS
        ]
        if not filtered_tokens:
            return subquery.strip()
        return " ".join(filtered_tokens)

    @classmethod
    def _comparison_question_score(cls, subquery: str, candidate: CandidateChunk) -> float:
        qa_pair = cls._extract_direct_qa_pair(candidate.text)
        candidate_question = qa_pair[0] if qa_pair is not None else candidate.text
        query_tokens = cls._comparison_match_tokens(subquery, drop_generic=True)
        candidate_tokens = cls._comparison_match_tokens(candidate_question)
        if not query_tokens or not candidate_tokens:
            return 0.0

        overlap = query_tokens & candidate_tokens
        if not overlap:
            return 0.0

        recall = len(overlap) / len(query_tokens)
        precision = len(overlap) / len(candidate_tokens)
        return (2 * recall * precision) / (recall + precision)

    @classmethod
    def _comparison_match_tokens(
        cls,
        text: str,
        *,
        drop_generic: bool = False,
    ) -> set[str]:
        tokens = [token for token in cls._tokenize(text) if len(token) > 2]
        if drop_generic and len(tokens) > 1:
            filtered_tokens = [
                token
                for token in tokens
                if token not in COMPARISON_GENERIC_TOKENS
            ]
            if filtered_tokens:
                tokens = filtered_tokens

        normalized_tokens: set[str] = set()
        for token in tokens:
            normalized_tokens.update(cls._comparison_token_variants(token))
        return normalized_tokens

    @staticmethod
    def _comparison_token_variants(token: str) -> set[str]:
        variants = {token}
        if len(token) > 4 and token.endswith("ies"):
            variants.add(f"{token[:-3]}y")
        if len(token) > 4 and token.endswith("es"):
            variants.add(token[:-2])
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            variants.add(token[:-1])
        return {variant for variant in variants if len(variant) > 2}

    def _comparison_contexts(
        self,
        question: str,
        *,
        collection_id: str,
        user_id: str,
    ) -> list[RetrievedContext]:
        subqueries = self._comparison_subqueries(question)
        if len(subqueries) < 2:
            return []

        target_collection = self._collection_name if collection_id == "all-pdfs" else collection_id
        contexts: list[RetrievedContext] = []
        seen_ids: set[str] = set()
        comparison_limit = max(self._top_k * 4, 10)
        for subquery in subqueries:
            search_query = self._comparison_search_query(subquery)
            lookup_query = (
                search_query
                if search_query.lower().startswith("what ")
                else f"what is {search_query}"
            )
            candidate_map: dict[str, CandidateChunk] = {}
            candidate_queries = [subquery]
            if search_query.lower() != subquery.lower():
                candidate_queries.append(search_query)
            if lookup_query.lower() not in {query.lower() for query in candidate_queries}:
                candidate_queries.append(lookup_query)

            for candidate_query in candidate_queries:
                for candidate in self._lexical_candidates_for_collection(
                    candidate_query,
                    target_collection,
                    user_id=user_id,
                    limit=comparison_limit,
                ):
                    candidate_map.setdefault(candidate.chunk_id, candidate)

            candidates = list(candidate_map.values())
            if not candidates:
                continue

            question_matched_pool = [
                candidate
                for candidate in candidates
                if self._comparison_question_score(subquery, candidate) > 0
            ] or candidates
            preferred_pool = [
                candidate
                for candidate in question_matched_pool
                if self._candidate_has_standalone_answer(candidate)
            ] or question_matched_pool

            rerank_scores = self._reranker_service.score_pairs(
                lookup_query,
                [candidate.text for candidate in preferred_pool],
            )
            best_index = max(
                range(len(preferred_pool)),
                key=lambda index: (
                    self._comparison_question_score(subquery, preferred_pool[index]),
                    1 if self._candidate_has_standalone_answer(preferred_pool[index]) else 0,
                    rerank_scores[index] if index < len(rerank_scores) else float("-inf"),
                ),
            )
            preferred_candidate = preferred_pool[best_index]
            if preferred_candidate is None or preferred_candidate.chunk_id in seen_ids:
                continue
            seen_ids.add(preferred_candidate.chunk_id)
            contexts.append(
                self._pdf_context_from_chunk(
                    RetrievedChunk(
                        chunk_id=preferred_candidate.chunk_id,
                        collection_id=preferred_candidate.collection_id,
                        document_id=preferred_candidate.document_id,
                        pdf_name=preferred_candidate.pdf_name,
                        page_number=preferred_candidate.page_number,
                        chunk_index=preferred_candidate.chunk_index,
                        text=preferred_candidate.text,
                    )
                )
            )

        return contexts

    def _direct_comparison_shortcut(
        self,
        question: str,
        contexts: Sequence[RetrievedContext],
    ) -> tuple[str, list[CitationPayload]] | None:
        if len(contexts) < 2:
            return None

        comparison_sentences: list[str] = []
        citations: list[CitationPayload] = []
        for index, context in enumerate(contexts[:2]):
            sentence = self._comparison_sentence_for_context(context)
            if not sentence:
                return None
            if index == 1:
                sentence = f"In contrast, {sentence[0].lower()}{sentence[1:]}" if len(sentence) > 1 else f"In contrast, {sentence.lower()}"
            comparison_sentences.append(sentence)
            citations.append(self._citation_from_context(context))

        answer = " ".join(comparison_sentences).strip()
        if not answer:
            return None
        return answer, citations

    @staticmethod
    def _first_sentence(text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return ""
        sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0].strip()
        if not sentence:
            return ""
        if sentence[-1] not in ".!?":
            sentence = f"{sentence}."
        return sentence

    def _comparison_sentence_for_context(self, context: RetrievedContext) -> str:
        qa_pair = self._extract_direct_qa_pair(context.text)
        if qa_pair is not None:
            candidate = self._first_sentence(qa_pair[1])
            if self._is_informative_answer_sentence(candidate):
                return candidate

        normalized = self._normalize_context_text(context.text)
        fallback = re.sub(
            r"^(?:\d{1,3}[.)]\s*)?.+?\?\s*",
            "",
            normalized,
            count=1,
            flags=re.DOTALL,
        )
        for sentence in re.split(r"(?<=[.!?])\s+", fallback):
            candidate = self._first_sentence(sentence)
            if self._is_informative_answer_sentence(candidate):
                return candidate
        return ""

    def _candidate_has_standalone_answer(self, candidate: CandidateChunk) -> bool:
        qa_pair = self._extract_direct_qa_pair(candidate.text)
        if qa_pair is None:
            return False
        answer_sentence = self._first_sentence(qa_pair[1])
        return self._is_informative_answer_sentence(answer_sentence)

    @staticmethod
    def _is_informative_answer_sentence(sentence: str) -> bool:
        if not sentence:
            return False
        if sentence.endswith("?"):
            return False
        if LOW_SIGNAL_ANSWER_PREFIX_PATTERN.match(sentence):
            return False
        return len(TOKEN_PATTERN.findall(sentence)) >= 4

    def _vector_candidates_for_collection(
        self,
        query_embedding: list[float],
        collection_id: str,
        *,
        user_id: str,
        limit: int,
    ) -> list[CandidateChunk]:
        collection = self._chroma_store.collection(self._collection_name)
        where_filter = self._where_filter(collection_id, user_id=user_id)
        vector_rows = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        candidates: list[CandidateChunk] = []
        for rank, (chunk_id, text, metadata) in enumerate(
            zip(
                vector_rows.get("ids", [[]])[0],
                vector_rows.get("documents", [[]])[0],
                vector_rows.get("metadatas", [[]])[0],
                strict=False,
            ),
        ):
            candidates.append(
                CandidateChunk(
                    chunk_id=str(chunk_id),
                    collection_id=collection_id,
                    document_id=str(metadata["document_id"]),
                    pdf_name=str(metadata["pdf_name"]),
                    page_number=int(metadata["page_number"]),
                    chunk_index=int(metadata["chunk_index"]),
                    text=str(text),
                    fused_score=self._rrf_score(rank),
                )
            )
        return candidates

    def _fallback_chunks(
        self,
        question: str,
        query_embedding: list[float],
        *,
        user_id: str,
    ) -> RetrievalResult:
        all_chunks = self._hybrid_candidates_for_collection(
            question,
            query_embedding,
            self._collection_name,
            user_id=user_id,
        )
        if not all_chunks:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        rerank_scores = self._reranker_service.score_pairs(
            question,
            [candidate.text for candidate in all_chunks],
        )
        for candidate, score in zip(all_chunks, rerank_scores, strict=False):
            candidate.rerank_score = score

        reranked = sorted(
            all_chunks,
            key=lambda chunk: (
                chunk.rerank_score if chunk.rerank_score is not None else float("-inf"),
                chunk.fused_score,
            ),
            reverse=True,
        )[: self._top_k]

        return RetrievalResult(
            chunks=[
                RetrievedChunk(
                    chunk_id=candidate.chunk_id,
                    collection_id=candidate.collection_id,
                    document_id=candidate.document_id,
                    pdf_name=candidate.pdf_name,
                    page_number=candidate.page_number,
                    chunk_index=candidate.chunk_index,
                    text=candidate.text,
                )
                for candidate in reranked
            ],
            top_rerank_score=reranked[0].rerank_score if reranked else None,
        )

    def _build_prompt(
        self,
        *,
        question: str,
        contexts: list[RetrievedContext],
        history_messages: Sequence[dict[str, str]],
    ) -> str:
        prompt_sections = [
            "Use only the retrieved evidence below to answer the user's question.",
            "Each evidence block starts with an exact source marker. Reuse a marker verbatim only when you need to cite directly.",
        ]
        pdf_contexts = [context for context in contexts if context.kind == "pdf"]
        web_contexts = [context for context in contexts if context.kind == "web"]
        user_history = [message for message in history_messages if message.get("role") == "user"]

        if pdf_contexts:
            prompt_sections.append(
                "PDF context:\n"
                + "\n\n".join(
                    self._render_context_for_prompt(question=question, context=context)
                    for context in pdf_contexts
                )
            )

        if web_contexts:
            prompt_sections.append(
                "Web search context:\n"
                + "\n\n".join(
                    self._render_context_for_prompt(question=question, context=context)
                    for context in web_contexts
                )
            )

        if user_history and looks_context_dependent(question):
            rendered_history = "\n".join(
                f"User: {message['content']}"
                for message in user_history[-PROMPT_HISTORY_USER_MESSAGE_LIMIT:]
            )
            prompt_sections.append(
                "Recent user messages for conversational context only (not evidence):\n"
                f"{rendered_history}"
            )

        prompt_sections.append(
            f"Question: {question}\n\n"
            "Answer in plain prose. Prefer one to three short paragraphs unless the user asks for a list or more detail. "
            "If the user asks for a specific sentence count or a brief answer, honor that strictly. "
            "Keep the answer tightly grounded in the evidence. If you include a source marker, copy it exactly from the context."
        )
        return "\n\n".join(prompt_sections)

    def _direct_context_shortcut(
        self,
        question: str,
        contexts: list[RetrievedContext],
    ) -> FinalizedAnswer | None:
        best_context: RetrievedContext | None = None
        best_answer: str | None = None
        best_rank: tuple[int, float, int] | None = None
        for context in contexts:
            if context.kind != "pdf":
                continue
            qa_pair = self._extract_direct_qa_pair(context.text)
            if qa_pair is None:
                continue
            qa_question, qa_answer = qa_pair
            question_score = self._question_match_score(question, qa_question)
            if question_score < DIRECT_QA_MATCH_THRESHOLD:
                continue
            cleaned_answer = self._clean_context_snippet(
                qa_answer,
                max_chars=CONTEXT_FALLBACK_CHAR_LIMIT * 2,
            )
            if not cleaned_answer:
                continue
            cleaned_answer = self._shape_shortcut_answer(question, cleaned_answer)
            first_sentence = self._first_sentence(cleaned_answer)
            candidate_rank = (
                1 if self._is_informative_answer_sentence(first_sentence) else 0,
                question_score,
                len(self._tokenize(cleaned_answer)),
            )
            if best_rank is None or candidate_rank > best_rank:
                best_rank = candidate_rank
                best_context = context
                best_answer = cleaned_answer

        if best_context is None or best_answer is None:
            return None
        return FinalizedAnswer(
            answer=best_answer,
            citations=[self._citation_from_context(best_context)],
        )

    def _direct_lexical_shortcut(
        self,
        question: str,
        *,
        collection_id: str,
        user_id: str,
    ) -> tuple[RetrievedContext, str] | None:
        lexical_contexts = [
            self._pdf_context_from_chunk(
                RetrievedChunk(
                    chunk_id=candidate.chunk_id,
                    collection_id=candidate.collection_id,
                    document_id=candidate.document_id,
                    pdf_name=candidate.pdf_name,
                    page_number=candidate.page_number,
                    chunk_index=candidate.chunk_index,
                    text=candidate.text,
                )
            )
            for candidate in self._lexical_candidates_for_collection(
                question,
                self._collection_name if collection_id == "all-pdfs" else collection_id,
                user_id=user_id,
                limit=max(self._top_k * 4, 12),
            )
        ]
        best_match: tuple[tuple[int, float, int], RetrievedContext, str] | None = None
        for context in lexical_contexts:
            qa_pair = self._extract_direct_qa_pair(context.text)
            if qa_pair is None:
                continue
            qa_question, qa_answer = qa_pair
            question_score = self._question_match_score(question, qa_question)
            if question_score < DIRECT_QA_MATCH_THRESHOLD:
                continue
            cleaned_answer = self._clean_context_snippet(
                qa_answer,
                max_chars=CONTEXT_FALLBACK_CHAR_LIMIT * 2,
            )
            if not cleaned_answer:
                continue
            cleaned_answer = self._shape_shortcut_answer(question, cleaned_answer)
            first_sentence = self._first_sentence(cleaned_answer)
            candidate_rank = (
                1 if self._is_informative_answer_sentence(first_sentence) else 0,
                question_score,
                len(self._tokenize(cleaned_answer)),
            )
            if best_match is None or candidate_rank > best_match[0]:
                best_match = (candidate_rank, context, cleaned_answer)
        if best_match is None:
            return None
        _rank, best_context, best_answer = best_match
        return best_context, best_answer

    @classmethod
    def _extract_direct_qa_pair(cls, text: str) -> tuple[str, str] | None:
        normalized_text = cls._normalize_context_text(text)
        match = DIRECT_QA_PATTERN.match(normalized_text)
        if not match:
            return None

        if match.group("question") and match.group("answer"):
            question = cls._clean_context_snippet(match.group("question"), max_chars=CONTEXT_FALLBACK_CHAR_LIMIT)
            answer = cls._clean_qa_answer_text(match.group("answer"))
            return (question, answer) if question and answer else None

        numbered_text = re.sub(r"^\s*\d{1,3}[.)]\s*", "", normalized_text)
        question_boundaries = [
            question_mark.end()
            for question_mark in re.finditer(r"\?", numbered_text[: CONTEXT_FALLBACK_CHAR_LIMIT * 2])
        ]
        for boundary in reversed(question_boundaries):
            numbered_question = cls._clean_context_snippet(
                numbered_text[:boundary],
                max_chars=CONTEXT_FALLBACK_CHAR_LIMIT,
            )
            numbered_answer = cls._clean_qa_answer_text(numbered_text[boundary:])
            if numbered_question and numbered_answer:
                return numbered_question, numbered_answer

        numbered_question = cls._clean_context_snippet(
            re.sub(r"^\d{1,3}[.)]\s*", "", match.group("numbered_question") or ""),
            max_chars=CONTEXT_FALLBACK_CHAR_LIMIT,
        )
        numbered_answer = cls._clean_qa_answer_text(match.group("numbered_answer") or "")
        return (numbered_question, numbered_answer) if numbered_question and numbered_answer else None

    @classmethod
    def _clean_qa_answer_text(cls, text: str) -> str:
        cleaned = re.sub(r"^\s*answer:\s*", "", text or "", flags=re.IGNORECASE).strip()
        repeated_question_match = re.match(
            r"^(?:question:\s*|(?:\d{1,3}[.)]\s*))?(?P<question>.+?\?)\s*(?P<rest>.+)$",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if repeated_question_match and repeated_question_match.group("rest").strip():
            cleaned = repeated_question_match.group("rest").strip()
        return cls._clean_context_snippet(
            cleaned,
            max_chars=CONTEXT_FALLBACK_CHAR_LIMIT * 2,
        )

    @classmethod
    def _question_match_score(cls, user_question: str, candidate_question: str) -> float:
        user_tokens = {
            token
            for token in cls._tokenize(cls._normalize_question_for_matching(user_question))
            if len(token) > 2
        }
        candidate_tokens = {
            token
            for token in cls._tokenize(candidate_question)
            if len(token) > 2
        }
        if len(user_tokens) < DIRECT_QA_MIN_TOKEN_COUNT or len(candidate_tokens) < DIRECT_QA_MIN_TOKEN_COUNT:
            return 0.0
        overlap = user_tokens & candidate_tokens
        if not overlap:
            return 0.0
        return len(overlap) / max(1, min(len(user_tokens), len(candidate_tokens)))

    @staticmethod
    def _normalize_question_for_matching(question: str) -> str:
        normalized = " ".join(question.strip().split())
        normalized = re.sub(
            r"\b(?:based only on|based on|using only)\b.*$",
            "",
            normalized,
            flags=re.IGNORECASE,
        ).strip()
        normalized = re.sub(
            r"\b(?:in|with)\s+(?:one|two|three|1|2|3)\s+(?:short\s+)?sentences?\b.*$",
            "",
            normalized,
            flags=re.IGNORECASE,
        ).strip()
        return normalized or question

    @classmethod
    def _shape_shortcut_answer(cls, question: str, answer: str) -> str:
        normalized_answer = cls._normalize_answer_text(answer)
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", normalized_answer)
            if sentence.strip()
        ]
        if not sentences:
            return normalized_answer

        if ONE_SENTENCE_PATTERN.search(question):
            return sentences[0]
        if TWO_SENTENCE_PATTERN.search(question):
            return " ".join(sentences[:2])
        if THREE_SENTENCE_PATTERN.search(question):
            return " ".join(sentences[:3])
        if CONCISE_ANSWER_PATTERN.search(question):
            return " ".join(sentences[:2])
        return normalized_answer

    def _fallback_finalized_answer(
        self,
        contexts: list[RetrievedContext],
        *,
        generation_warning: str,
    ) -> FinalizedAnswer:
        for context in contexts:
            if context.kind != "pdf":
                continue
            qa_pair = self._extract_direct_qa_pair(context.text)
            if qa_pair is None:
                continue
            _qa_question, qa_answer = qa_pair
            if qa_answer:
                return FinalizedAnswer(
                    answer=qa_answer,
                    citations=[self._citation_from_context(context)],
                    generation_warning=generation_warning,
                )

        best_contexts = contexts[:2]
        fallback_passages = [
            self._clean_context_snippet(context.text, max_chars=CONTEXT_FALLBACK_CHAR_LIMIT)
            for context in best_contexts
        ]
        fallback_answer = "\n\n".join(
            passage
            for passage in fallback_passages
            if passage
        ).strip()
        if not fallback_answer:
            fallback_answer = self._ungrounded_answer_message()
        return FinalizedAnswer(
            answer=fallback_answer,
            citations=[self._citation_from_context(context) for context in best_contexts],
            generation_warning=generation_warning,
        )

    @staticmethod
    def _is_interactive_timeout(error: Exception) -> bool:
        return isinstance(error, (httpx.TimeoutException, TimeoutError))

    @staticmethod
    def _normalize_context_text(text: str) -> str:
        cleaned = PREVIEW_NOISE_LINE_PATTERN.sub("", text or "")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @classmethod
    def _clean_context_snippet(cls, text: str, *, max_chars: int) -> str:
        normalized = cls._normalize_context_text(text)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return cls._trim_text(normalized, max_chars) if normalized else ""

    @staticmethod
    def _interactive_generation_options(
        *,
        question: str,
        contexts: list[RetrievedContext],
    ) -> dict[str, float | int]:
        has_pdf_context = any(context.kind == "pdf" for context in contexts)
        has_web_context = any(context.kind == "web" for context in contexts)
        if has_pdf_context and has_web_context:
            num_predict = 320
        elif has_pdf_context:
            num_predict = 384
        else:
            num_predict = 256

        if ONE_SENTENCE_PATTERN.search(question):
            num_predict = min(num_predict, 96)
        elif TWO_SENTENCE_PATTERN.search(question):
            num_predict = min(num_predict, 128)
        elif THREE_SENTENCE_PATTERN.search(question):
            num_predict = min(num_predict, 176)
        elif CONCISE_ANSWER_PATTERN.search(question):
            num_predict = min(num_predict, 224)

        return {
            "temperature": 0.05,
            "num_predict": num_predict,
        }

    def _render_context_for_prompt(
        self,
        *,
        question: str,
        context: RetrievedContext,
    ) -> str:
        max_chars = (
            PROMPT_WEB_CONTEXT_CHAR_LIMIT
            if context.kind == "web"
            else PROMPT_PDF_CONTEXT_CHAR_LIMIT
        )
        return (
            f"{context.label}\n"
            f"{self._focus_context_text(question=question, text=context.text, max_chars=max_chars)}"
        )

    def _focus_context_text(
        self,
        *,
        question: str,
        text: str,
        max_chars: int,
    ) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) <= max_chars:
            return normalized

        query_tokens = {
            token
            for token in self._tokenize(question)
            if len(token) > 2
        }
        if not query_tokens:
            return self._trim_text(normalized, max_chars)

        stride = max(120, max_chars // 3)
        max_start = max(len(normalized) - max_chars, 0)
        window_starts = list(range(0, max_start + 1, stride)) or [0]
        if window_starts[-1] != max_start:
            window_starts.append(max_start)

        best_start = 0
        best_score = -1
        for start in window_starts:
            candidate = normalized[start : start + max_chars]
            score = len(query_tokens & set(self._tokenize(candidate)))
            if score > best_score:
                best_score = score
                best_start = start

        return self._trim_text_window(normalized, best_start, max_chars)

    @staticmethod
    def _trim_text(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        snippet = text[:max_chars].rstrip()
        last_space = snippet.rfind(" ")
        if last_space >= max_chars // 2:
            snippet = snippet[:last_space]
        return f"{snippet.rstrip(' ,;:')}..."

    @staticmethod
    def _trim_text_window(text: str, start: int, max_chars: int) -> str:
        max_start = max(len(text) - max_chars, 0)
        start = max(0, min(start, max_start))
        end = min(len(text), start + max_chars)

        if start > 0:
            while start < end and not text[start].isspace():
                start += 1
        if end < len(text):
            while end > start and not text[end - 1].isspace():
                end -= 1

        snippet = text[start:end].strip()
        if not snippet:
            return RagService._trim_text(text, max_chars)

        if start > 0:
            snippet = f"...{snippet}"
        if end < len(text):
            snippet = f"{snippet.rstrip(' ,;:')}..."
        return snippet

    def _extract_citations(
        self,
        answer: str,
        contexts: list[RetrievedContext],
    ) -> list[CitationPayload]:
        by_key: dict[str, CitationPayload] = {}
        pdf_id_lookup = {
            context.id: context
            for context in contexts
            if context.kind == "pdf"
        }
        pdf_lookup: dict[tuple[str, int, int], RetrievedContext] = {}
        pdf_page_lookup: dict[tuple[str, int], list[RetrievedContext]] = {}
        for context in contexts:
            if context.kind != "pdf" or context.pdf_name is None or context.page_number is None:
                continue
            if context.chunk_index is not None:
                pdf_lookup[(context.pdf_name, context.page_number, context.chunk_index)] = context
            pdf_page_lookup.setdefault((context.pdf_name, context.page_number), []).append(context)
        web_lookup = {
            context.url: context
            for context in contexts
            if context.kind == "web" and context.url is not None
        }

        for match in PDF_CITATION_PATTERN.finditer(answer):
            context = pdf_id_lookup.get(match.group("id").strip())
            if context is None:
                continue
            by_key[context.id] = CitationPayload(
                id=context.id,
                kind="pdf",
                document_id=context.document_id,
                pdf_name=context.pdf_name,
                page=context.page_number,
                chunk_index=context.chunk_index,
                excerpt=context.excerpt,
                title=context.title,
                url=context.url,
            )

        for match in LEGACY_PDF_CITATION_PATTERN.finditer(answer):
            pdf_name = match.group("pdf").strip()
            page_number = int(match.group("page"))
            chunk_group = match.group("chunk")
            chunk_index = int(chunk_group) - 1 if chunk_group is not None else None
            context = (
                pdf_lookup.get((pdf_name, page_number, chunk_index))
                if chunk_index is not None
                else None
            )
            if context is None:
                page_contexts = pdf_page_lookup.get((pdf_name, page_number), [])
                context = self._best_page_context(answer, match.start(), page_contexts)
            if context is None:
                continue
            by_key[context.id] = CitationPayload(
                id=context.id,
                kind="pdf",
                document_id=context.document_id,
                pdf_name=context.pdf_name,
                page=context.page_number,
                chunk_index=context.chunk_index,
                excerpt=context.excerpt,
                title=context.title,
                url=context.url,
            )

        for match in WEB_CITATION_PATTERN.finditer(answer):
            url = match.group("url").strip()
            context = web_lookup.get(url)
            if context is None:
                continue
            by_key[context.id] = CitationPayload(
                id=context.id,
                kind="web",
                pdf_name=None,
                page=None,
                chunk_index=None,
                excerpt=context.excerpt,
                title=context.title,
                url=context.url,
            )

        return list(by_key.values())

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return TOKEN_PATTERN.findall(text.lower())

    def _build_fts_query(self, text: str) -> str:
        tokens = self._tokenize(text)
        if not tokens:
            return ""
        unique_tokens: list[str] = []
        seen_tokens: set[str] = set()
        for token in tokens:
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            unique_tokens.append(token)
        return " OR ".join(f'"{token}"' for token in unique_tokens)

    @staticmethod
    def _rrf_score(rank: int) -> float:
        return 1.0 / (RRF_K + rank + 1)

    def _pdf_context_from_chunk(self, chunk: RetrievedChunk) -> RetrievedContext:
        context_id = chunk.chunk_id
        return RetrievedContext(
            id=context_id,
            kind="pdf",
            label=f"[SourceID: {context_id}]",
            text=chunk.text,
            excerpt=self._clean_context_snippet(chunk.text, max_chars=280),
            document_id=chunk.document_id,
            pdf_name=chunk.pdf_name,
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
        )

    def _select_contexts(
        self,
        pdf_contexts: list[RetrievedContext],
        web_contexts: list[RetrievedContext],
    ) -> list[RetrievedContext]:
        selected_pdf_contexts = pdf_contexts[: min(PROMPT_PDF_CONTEXT_LIMIT, self._top_k)]
        selected_web_contexts = web_contexts[: min(PROMPT_WEB_CONTEXT_LIMIT, self._top_k)]
        return [*selected_pdf_contexts, *selected_web_contexts]

    def _web_contexts_from_results(self, results: list[WebSearchResult]) -> list[RetrievedContext]:
        return [
            RetrievedContext(
                id=f"web:{index}:{result.url}",
                kind="web",
                label=f"[Web: {result.url}]",
                text="\n".join(
                    part
                    for part in (
                        result.title,
                        f"Published: {result.published_at}" if result.published_at else None,
                        result.content,
                    )
                    if part
                ),
                excerpt=result.content[:280],
                url=result.url,
                title=result.title,
            )
            for index, result in enumerate(results)
        ]

    def _rerank_web_results(
        self,
        query: str,
        results: list[WebSearchResult],
    ) -> list[WebSearchResult]:
        if not results:
            return []

        passages = [
            "\n".join(part for part in (result.title, result.snippet, result.content[:1600]) if part)
            for result in results
        ]
        rerank_scores = self._reranker_service.score_pairs(query, passages)
        scored_results = []
        for result, rerank_score in zip(results, rerank_scores, strict=False):
            freshness_bonus = self._web_result_freshness_bonus(query, result)
            scored_results.append((rerank_score + freshness_bonus, result))

        scored_results.sort(key=lambda item: item[0], reverse=True)
        return [result for _score, result in scored_results]

    def _web_result_freshness_bonus(self, query: str, result: WebSearchResult) -> float:
        bonus = 0.0
        query_text = query.lower()
        result_text = f"{result.title} {result.snippet}".lower()
        current_intent = any(
            token in query_text
            for token in ("latest", "current", "today", "recent", "new", "stable", "version", "release")
        )

        if current_intent and any(
            token in result_text
            for token in ("latest", "current", "stable", "release notes", "changelog", "version")
        ):
            bonus += 0.12

        if result.published_at:
            year_match = re.search(r"(20\d{2})", result.published_at)
            if year_match:
                current_year = datetime.now(UTC).year
                year = int(year_match.group(1))
                if year >= current_year:
                    bonus += 0.16
                elif year == current_year - 1:
                    bonus += 0.08
                elif current_intent:
                    bonus -= min(0.12, 0.03 * max(current_year - year - 1, 0))

        return bonus

    def _should_use_web_search(self, top_rerank_score: float | None) -> bool:
        if top_rerank_score is None:
            return False
        return top_rerank_score < self._web_search_score_threshold

    def _has_local_context(self, collection_id: str, *, user_id: str) -> bool:
        if collection_id == "all-pdfs":
            return self._document_service.count_indexed_chunks(user_id=user_id) > 0

        for topic in self._kg_manager.topic_summaries(user_id):
            if topic.id == collection_id:
                return topic.chunk_count > 0
        return False

    @staticmethod
    def _no_context_message(*, web_search_enabled: bool, offline_warning: str | None) -> str:
        if offline_warning:
            return (
                f"{offline_warning} "
                "Your PDFs do not contain enough information to answer that confidently."
            )
        if web_search_enabled:
            return (
                "I couldn't find enough relevant information in your PDFs or from web search "
                "to answer that confidently."
            )
        return "I couldn't find enough support in your PDFs to answer that confidently."

    @staticmethod
    def _ungrounded_answer_message() -> str:
        return "I couldn't ground a confident answer in the retrieved sources."

    @staticmethod
    def _reasoning_segments_from(label: str, thinking: str | None) -> list[str]:
        cleaned = (thinking or "").strip()
        if not cleaned:
            return []
        return [f"{label}: {cleaned}"]

    @staticmethod
    def _reasoning_context_summary(contexts: list[RetrievedContext]) -> str:
        if not contexts:
            return ""
        pdf_count = sum(1 for context in contexts if context.kind == "pdf")
        web_count = sum(1 for context in contexts if context.kind == "web")
        parts = []
        if pdf_count:
            parts.append(f"{pdf_count} PDF excerpt{'s' if pdf_count != 1 else ''}")
        if web_count:
            parts.append(f"{web_count} web result{'s' if web_count != 1 else ''}")
        return ", ".join(parts)

    @classmethod
    def _clean_model_thinking_summary(cls, summary: str) -> str | None:
        cleaned = cls._strip_thinking_blocks(summary)
        cleaned = re.sub(r"\[SourceID:[^\]]+\]", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\[Web:[^\]]+\]", "", cleaned, flags=re.IGNORECASE)
        cleaned = MODEL_THINKING_SENSITIVE_LINE_PATTERN.sub("", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if not cleaned:
            return None
        if "reasoning summary" not in cleaned[:80].lower():
            cleaned = f"Reasoning summary\n\n{cleaned}"
        return cleaned[:1400].rstrip()

    @staticmethod
    def _strip_thinking_blocks(answer: str) -> str:
        without_closed_blocks = THINK_BLOCK_PATTERN.sub("", answer)
        return OPEN_THINK_BLOCK_PATTERN.sub("", without_closed_blocks).strip()

    @staticmethod
    def _strip_citation_markers(answer: str) -> str:
        stripped = PDF_CITATION_PATTERN.sub("", answer)
        stripped = LEGACY_PDF_CITATION_PATTERN.sub("", stripped)
        stripped = WEB_CITATION_PATTERN.sub("", stripped)
        return re.sub(r"\s{2,}", " ", stripped)

    @staticmethod
    def _normalize_answer_text(answer: str) -> str:
        normalized = re.sub(r"\s+([,.;:!?])", r"\1", answer)
        normalized = re.sub(r"([(\[])\s+", r"\1", normalized)
        normalized = re.sub(r"\s+([)\]])", r"\1", normalized)
        normalized = re.sub(r"\s{2,}", " ", normalized).strip()
        if normalized.endswith('"') and not normalized.startswith('"'):
            normalized = normalized[:-1].rstrip()
        if normalized.endswith("'") and not normalized.startswith("'"):
            normalized = normalized[:-1].rstrip()
        return normalized

    def _best_page_context(
        self,
        answer: str,
        marker_start: int,
        page_contexts: list[RetrievedContext],
    ) -> RetrievedContext | None:
        if not page_contexts:
            return None
        if len(page_contexts) == 1:
            return page_contexts[0]

        claim_tokens = set(self._tokenize(self._claim_window(answer, marker_start)))
        if not claim_tokens:
            return page_contexts[0]

        return max(
            page_contexts,
            key=lambda context: len(claim_tokens & set(self._tokenize(context.text))),
        )

    @staticmethod
    def _claim_window(answer: str, marker_start: int) -> str:
        window_start = max(0, marker_start - 260)
        prefix = answer[window_start:marker_start]
        boundary = max(prefix.rfind("."), prefix.rfind("!"), prefix.rfind("?"), prefix.rfind("\n"))
        if boundary >= 0:
            prefix = prefix[boundary + 1 :]
        return prefix.strip()

    @staticmethod
    def _substantive_segments(answer: str) -> list[str]:
        segments: list[str] = []
        for segment in re.split(r"(\n\s*\n+)", answer.strip()):
            if not segment or segment.isspace():
                continue
            if not TOKEN_PATTERN.search(segment):
                continue
            segments.append(segment.strip())
        return segments

    def _has_uncited_substantive_segments(
        self,
        answer: str,
        contexts: list[RetrievedContext],
    ) -> bool:
        for segment in self._substantive_segments(answer):
            if (
                PDF_CITATION_PATTERN.search(segment)
                or LEGACY_PDF_CITATION_PATTERN.search(segment)
                or WEB_CITATION_PATTERN.search(segment)
            ):
                continue
            if self._best_context_for_segment(segment, contexts) is None:
                return True
        return False

    @staticmethod
    def _references_unknown_sources(answer: str, contexts: list[RetrievedContext]) -> bool:
        known_pdf_ids = {
            context.id
            for context in contexts
            if context.kind == "pdf"
        }
        known_pdf_pages = {
            (context.pdf_name, context.page_number)
            for context in contexts
            if context.kind == "pdf"
            and context.pdf_name is not None
            and context.page_number is not None
        }
        known_web_urls = {
            context.url
            for context in contexts
            if context.kind == "web" and context.url is not None
        }

        for match in PDF_CITATION_PATTERN.finditer(answer):
            if match.group("id").strip() not in known_pdf_ids:
                return True

        for match in LEGACY_PDF_CITATION_PATTERN.finditer(answer):
            pdf_name = match.group("pdf").strip()
            page_number = int(match.group("page"))
            if (pdf_name, page_number) not in known_pdf_pages:
                return True

        for match in WEB_CITATION_PATTERN.finditer(answer):
            if match.group("url").strip() not in known_web_urls:
                return True

        return False

    def _derive_citations_from_answer(
        self,
        answer: str,
        contexts: list[RetrievedContext],
    ) -> list[CitationPayload]:
        citations_by_id: dict[str, CitationPayload] = {}
        for segment in self._substantive_segments(answer):
            context = self._best_context_for_segment(segment, contexts)
            if context is None:
                return []
            citations_by_id[context.id] = self._citation_from_context(context)
        return list(citations_by_id.values())

    def _best_context_for_segment(
        self,
        segment: str,
        contexts: list[RetrievedContext],
    ) -> RetrievedContext | None:
        segment_tokens = set(self._tokenize(segment))
        if len(segment_tokens) < 2:
            return None

        best_context: RetrievedContext | None = None
        best_score = 0.0
        best_overlap = 0
        for context in contexts:
            context_tokens = set(self._tokenize(context.text))
            overlap = segment_tokens & context_tokens
            if not overlap:
                continue

            score = len(overlap) / max(len(segment_tokens), 1)
            if context.title:
                title_tokens = set(self._tokenize(context.title))
                if title_tokens:
                    score += 0.2 * (len(segment_tokens & title_tokens) / len(title_tokens))

            if score > best_score or (score == best_score and len(overlap) > best_overlap):
                best_context = context
                best_score = score
                best_overlap = len(overlap)

        if best_context is None:
            return None

        minimum_overlap = 3 if len(segment_tokens) >= 6 else 2
        if best_overlap < minimum_overlap and best_score < 0.2:
            return None
        return best_context

    @staticmethod
    def _citation_from_context(context: RetrievedContext) -> CitationPayload:
        if context.kind == "web":
            return CitationPayload(
                id=context.id,
                kind="web",
                pdf_name=None,
                page=None,
                chunk_index=None,
                excerpt=context.excerpt,
                title=context.title,
                url=context.url,
            )

        return CitationPayload(
            id=context.id,
            kind="pdf",
            document_id=context.document_id,
            pdf_name=context.pdf_name,
            page=context.page_number,
            chunk_index=context.chunk_index,
            excerpt=context.excerpt,
            title=context.title,
            url=context.url,
        )

    def _where_filter(self, collection_id: str, *, user_id: str) -> dict[str, object]:
        if collection_id == self._collection_name:
            return {"$and": [{"user_id": user_id}, {"is_indexed": 1}]}
        return {
            "$and": [
                {"user_id": user_id},
                {"is_indexed": 1},
                {"collection_id": collection_id},
            ]
        }
