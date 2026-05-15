from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Sequence

import httpx

from app.core.chroma_store import ChromaStore
from app.models.schemas import CitationPayload, ToolCallPayload
from app.services.document_service import DocumentService
from app.services.kg_manager import KgManager
from app.services.message_intent import classify_message_intent
from app.services.ollama_client import OllamaClient, OllamaGenerationResult
from app.services.query_rewrite_service import QueryRewriteService
from app.services.rag_answer_text import (
    CONCISE_ANSWER_PATTERN,
    LEGACY_PDF_CITATION_PATTERN,
    ONE_SENTENCE_PATTERN,
    PDF_CITATION_PATTERN,
    THREE_SENTENCE_PATTERN,
    TWO_SENTENCE_PATTERN,
    WEB_CITATION_PATTERN,
    best_page_context,
    clean_model_thinking_summary,
    derive_citations_from_answer,
    extract_direct_qa_pair,
    has_uncited_substantive_segments,
    normalize_answer_text,
    question_match_score,
    references_unknown_sources,
    shape_shortcut_answer,
    strip_citation_markers,
    strip_thinking_blocks,
    tokenize,
)
from app.services.rag_comparison import (
    comparison_question_score,
    comparison_search_query,
    comparison_subqueries,
)
from app.services.rag_citations import (
    citation_from_context,
    docling_source_metadata_from_metadata,
    pdf_context_from_chunk,
    retrieved_chunk_from_candidate,
)
from app.services.rag_grounding import (
    CONTEXT_FALLBACK_CHAR_LIMIT,
    clean_context_snippet,
    compose_fallback_answer,
    grounding_system_prompt,
    no_context_message,
    normalize_context_text,
    trim_text,
    ungrounded_answer_message,
)
from app.services.rag_prompting import (
    build_prompt,
    select_contexts,
)
from app.services.rag_types import (
    CandidateChunk,
    FinalizedAnswer,
    PreparedAnswer,
    RetrievalResult,
    RetrievedChunk,
    RetrievedContext,
)
from app.services.reranker_service import RerankerService
from app.services.web_search_service import WebSearchError, WebSearchOfflineError, WebSearchResult, WebSearchService


RRF_K = 60
INTERACTIVE_RETRIEVAL_EMBED_TIMEOUT_SECONDS = 20.0
INTERACTIVE_THINKING_GENERATE_TIMEOUT_SECONDS = 15.0
INTERACTIVE_GENERATE_TIMEOUT_SECONDS = 45.0
MODEL_THINKING_SUMMARY_TIMEOUT_SECONDS = 18.0
MIN_TOPIC_RETRIEVAL_CANDIDATES = 5
DIRECT_QA_MATCH_THRESHOLD = 0.7
MIN_INTERACTIVE_RERANK_CANDIDATES = 6
MAX_INTERACTIVE_RERANK_CANDIDATES = 8
DOMINANT_RESULT_SHARE = 0.75
FUSED_SCORE_DOMINANCE_MARGIN = 0.01
MODEL_THINKING_SEGMENT_CHAR_LIMIT = 2400
LOW_SIGNAL_ANSWER_PREFIX_PATTERN = re.compile(
    r"^(?:in the above|in the below|the above|the below|but\b|and the|getinstance\b)",
    re.IGNORECASE,
)
LOGGER = logging.getLogger(__name__)


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
            if prepared.contexts and last_result.answer == ungrounded_answer_message():
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
                shortcut_answer=no_context_message(
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
                shortcut_citations=[citation_from_context(shortcut_context)],
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
            prompt = build_prompt(
                question=question,
                contexts=comparison_contexts,
                history_messages=history_messages or [],
            )
            system_prompt = grounding_system_prompt()
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

        pdf_contexts = [pdf_context_from_chunk(chunk) for chunk in retrieval.chunks]
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
                shortcut_answer=no_context_message(
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

        prompt = build_prompt(
            question=question,
            contexts=contexts,
            history_messages=history_messages or [],
        )
        system_prompt = grounding_system_prompt()
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
        normalized_answer = strip_thinking_blocks(raw_answer.strip())
        clean_answer = normalize_answer_text(
            strip_citation_markers(normalized_answer).strip()
        )
        citations = self._extract_citations(normalized_answer, contexts)
        if not citations and contexts and clean_answer:
            citations = derive_citations_from_answer(clean_answer, contexts)
        if contexts and (
            not citations
            or references_unknown_sources(normalized_answer, contexts)
            or has_uncited_substantive_segments(normalized_answer, contexts)
        ):
            return ungrounded_answer_message(), []
        return clean_answer, citations

    def should_retry_without_thinking(
        self,
        answer: str,
        citations: list[CitationPayload],
        contexts: list[RetrievedContext],
    ) -> bool:
        return bool(contexts) and not citations and answer == ungrounded_answer_message()

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
        if contexts and not citations and answer == ungrounded_answer_message():
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
            trim_text(re.sub(r"\s+", " ", segment).strip(), MODEL_THINKING_SEGMENT_CHAR_LIMIT)
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

        return clean_model_thinking_summary(summary.response)

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
                retrieved_chunk_from_candidate(candidate)
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
                retrieved_chunk_from_candidate(candidate)
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
        metadata_by_chunk_id = self._metadata_by_chunk_id([row.chunk_id for row in rows])
        return [
            CandidateChunk(
                chunk_id=row.chunk_id,
                collection_id=row.collection_id or collection_id,
                document_id=row.document_id,
                pdf_name=row.pdf_name,
                page_number=row.page_number,
                chunk_index=row.chunk_index,
                text=row.text,
                **docling_source_metadata_from_metadata(
                    metadata_by_chunk_id.get(row.chunk_id, {})
                ),
            )
            for row in rows
        ]

    def _metadata_by_chunk_id(self, chunk_ids: Sequence[str]) -> dict[str, dict[str, object]]:
        if not chunk_ids:
            return {}
        try:
            rows = self._chroma_store.collection(self._collection_name).get(
                ids=list(chunk_ids),
                include=["metadatas"],
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning("Could not load chunk metadata for lexical citations.", exc_info=True)
            return {}

        return {
            str(chunk_id): dict(metadata or {})
            for chunk_id, metadata in zip(
                rows.get("ids", []),
                rows.get("metadatas", []),
                strict=False,
            )
        }

    def _merge_comparison_lexical_candidates(
        self,
        candidate_map: dict[str, CandidateChunk],
        *,
        question: str,
        collection_names: Sequence[str],
        user_id: str,
    ) -> None:
        subqueries = comparison_subqueries(question)
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
        if comparison_subqueries(question):
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
        if comparison_subqueries(question):
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
        subqueries = comparison_subqueries(question)
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

    def _comparison_contexts(
        self,
        question: str,
        *,
        collection_id: str,
        user_id: str,
    ) -> list[RetrievedContext]:
        subqueries = comparison_subqueries(question)
        if len(subqueries) < 2:
            return []

        target_collection = self._collection_name if collection_id == "all-pdfs" else collection_id
        contexts: list[RetrievedContext] = []
        seen_ids: set[str] = set()
        comparison_limit = max(self._top_k * 4, 10)
        for subquery in subqueries:
            search_query = comparison_search_query(subquery)
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
                if comparison_question_score(subquery, candidate) > 0
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
                    comparison_question_score(subquery, preferred_pool[index]),
                    1 if self._candidate_has_standalone_answer(preferred_pool[index]) else 0,
                    rerank_scores[index] if index < len(rerank_scores) else float("-inf"),
                ),
            )
            preferred_candidate = preferred_pool[best_index]
            if preferred_candidate is None or preferred_candidate.chunk_id in seen_ids:
                continue
            seen_ids.add(preferred_candidate.chunk_id)
            contexts.append(
                pdf_context_from_chunk(retrieved_chunk_from_candidate(preferred_candidate))
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
            citations.append(citation_from_context(context))

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
        qa_pair = extract_direct_qa_pair(context.text)
        if qa_pair is not None:
            candidate = self._first_sentence(qa_pair[1])
            if self._is_informative_answer_sentence(candidate):
                return candidate

        normalized = normalize_context_text(context.text)
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
        qa_pair = extract_direct_qa_pair(candidate.text)
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
        return len(tokenize(sentence)) >= 4

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
                    **docling_source_metadata_from_metadata(dict(metadata or {})),
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
                retrieved_chunk_from_candidate(candidate)
                for candidate in reranked
            ],
            top_rerank_score=reranked[0].rerank_score if reranked else None,
        )

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
            qa_pair = extract_direct_qa_pair(context.text)
            if qa_pair is None:
                continue
            qa_question, qa_answer = qa_pair
            question_score = question_match_score(question, qa_question)
            if question_score < DIRECT_QA_MATCH_THRESHOLD:
                continue
            cleaned_answer = clean_context_snippet(
                qa_answer,
                max_chars=CONTEXT_FALLBACK_CHAR_LIMIT * 2,
            )
            if not cleaned_answer:
                continue
            cleaned_answer = shape_shortcut_answer(question, cleaned_answer)
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
            citations=[citation_from_context(best_context)],
        )

    def _direct_lexical_shortcut(
        self,
        question: str,
        *,
        collection_id: str,
        user_id: str,
    ) -> tuple[RetrievedContext, str] | None:
        lexical_contexts = [
            pdf_context_from_chunk(retrieved_chunk_from_candidate(candidate))
            for candidate in self._lexical_candidates_for_collection(
                question,
                self._collection_name if collection_id == "all-pdfs" else collection_id,
                user_id=user_id,
                limit=max(self._top_k * 4, 12),
            )
        ]
        best_match: tuple[tuple[int, float, int], RetrievedContext, str] | None = None
        for context in lexical_contexts:
            qa_pair = extract_direct_qa_pair(context.text)
            if qa_pair is None:
                continue
            qa_question, qa_answer = qa_pair
            question_score = question_match_score(question, qa_question)
            if question_score < DIRECT_QA_MATCH_THRESHOLD:
                continue
            cleaned_answer = clean_context_snippet(
                qa_answer,
                max_chars=CONTEXT_FALLBACK_CHAR_LIMIT * 2,
            )
            if not cleaned_answer:
                continue
            cleaned_answer = shape_shortcut_answer(question, cleaned_answer)
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

    def _fallback_finalized_answer(
        self,
        contexts: list[RetrievedContext],
        *,
        generation_warning: str,
    ) -> FinalizedAnswer:
        fallback_answer = compose_fallback_answer(
            contexts,
            generation_warning=generation_warning,
            extract_direct_qa_pair=extract_direct_qa_pair,
        )
        return FinalizedAnswer(
            answer=fallback_answer.answer,
            citations=[
                citation_from_context(context)
                for context in fallback_answer.citation_contexts
            ],
            generation_warning=fallback_answer.generation_warning,
        )

    @staticmethod
    def _is_interactive_timeout(error: Exception) -> bool:
        return isinstance(error, (httpx.TimeoutException, TimeoutError))

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
            by_key[context.id] = citation_from_context(context)

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
                context = best_page_context(answer, match.start(), page_contexts)
            if context is None:
                continue
            by_key[context.id] = citation_from_context(context)

        for match in WEB_CITATION_PATTERN.finditer(answer):
            url = match.group("url").strip()
            context = web_lookup.get(url)
            if context is None:
                continue
            by_key[context.id] = citation_from_context(context)

        return list(by_key.values())

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return tokenize(text)

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

    def _select_contexts(
        self,
        pdf_contexts: list[RetrievedContext],
        web_contexts: list[RetrievedContext],
    ) -> list[RetrievedContext]:
        return select_contexts(pdf_contexts, web_contexts, top_k=self._top_k)

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
