from __future__ import annotations

import asyncio
import logging
import re
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
    DIRECT_QA_MATCH_THRESHOLD,
    LEGACY_PDF_CITATION_PATTERN,
    ONE_SENTENCE_PATTERN,
    PDF_CITATION_PATTERN,
    THREE_SENTENCE_PATTERN,
    TWO_SENTENCE_PATTERN,
    WEB_CITATION_PATTERN,
    best_page_context,
    clean_model_thinking_summary,
    comparison_sentence_for_context,
    derive_citations_from_answer,
    extract_direct_qa_pair,
    first_sentence,
    has_uncited_substantive_segments,
    is_informative_answer_sentence,
    normalize_answer_text,
    question_match_score,
    references_unknown_sources,
    shape_shortcut_answer,
    strip_citation_markers,
    strip_thinking_blocks,
    tokenize,
)
from app.services.rag_citations import (
    citation_from_context,
    pdf_context_from_chunk,
)
from app.services.rag_grounding import (
    CONTEXT_FALLBACK_CHAR_LIMIT,
    clean_context_snippet,
    compose_fallback_answer,
    grounding_system_prompt,
    no_context_message,
    trim_text,
    ungrounded_answer_message,
)
from app.services.rag_prompting import (
    build_prompt,
    select_contexts,
)
from app.services.rag_retrieval import RagRetrievalEngine
from app.services.rag_types import (
    FinalizedAnswer,
    PreparedAnswer,
    RetrievalResult,
    RetrievedContext,
)
from app.services.reranker_service import RerankerService
from app.services.web_search_service import WebSearchError, WebSearchOfflineError, WebSearchService


INTERACTIVE_RETRIEVAL_EMBED_TIMEOUT_SECONDS = 20.0
INTERACTIVE_THINKING_GENERATE_TIMEOUT_SECONDS = 15.0
INTERACTIVE_GENERATE_TIMEOUT_SECONDS = 45.0
MODEL_THINKING_SUMMARY_TIMEOUT_SECONDS = 18.0
MODEL_THINKING_SEGMENT_CHAR_LIMIT = 2400
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
        self._query_rewrite_service = query_rewrite_service
        self._web_search_service = web_search_service
        self._retrieval_engine = RagRetrievalEngine(
            chroma_store=chroma_store,
            document_service=document_service,
            kg_manager=kg_manager,
            reranker_service=reranker_service,
            collection_name=collection_name,
            top_k=top_k,
            web_search_score_threshold=web_search_score_threshold,
        )

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

        has_local_context = self._retrieval_engine.has_local_context(collection_id, user_id=user_id)
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
        lexical_shortcut = self._retrieval_engine.direct_lexical_shortcut(
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

        comparison_contexts = self._retrieval_engine.comparison_contexts(
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
                    self._retrieval_engine.retrieve_chunks_without_embedding,
                    retrieval_query,
                    collection_id,
                    user_id=user_id,
                )
            else:
                retrieval = await asyncio.to_thread(
                    self._retrieval_engine.retrieve_chunks,
                    retrieval_query,
                    query_embedding,
                    collection_id,
                    user_id=user_id,
                )
                if not retrieval.chunks and collection_id == "all-pdfs":
                    retrieval = await asyncio.to_thread(
                        self._retrieval_engine.fallback_chunks,
                        retrieval_query,
                        query_embedding,
                        user_id=user_id,
                    )

        pdf_contexts = [pdf_context_from_chunk(chunk) for chunk in retrieval.chunks]
        tool_call = (
            ToolCallPayload(label="Searched the web for", query=retrieval_query)
            if web_search_enabled
            and (not pdf_contexts or self._retrieval_engine.should_use_web_search(retrieval.top_rerank_score))
            else None
        )
        web_contexts: list[RetrievedContext] = []
        web_search_used = False
        offline_warning: str | None = None

        if tool_call is not None:
            try:
                web_results = await self._web_search_service.search(retrieval_query)
                web_results = await asyncio.to_thread(
                    self._retrieval_engine.rerank_web_results,
                    retrieval_query,
                    web_results,
                )
                web_contexts = self._retrieval_engine.web_contexts_from_results(web_results)
                web_search_used = bool(web_contexts)
            except WebSearchOfflineError as error:
                offline_warning = str(error)
            except WebSearchError as error:
                offline_warning = str(error)

        contexts = select_contexts(
            pdf_contexts,
            web_contexts,
            top_k=self._retrieval_engine.top_k,
        )
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
            sentence = comparison_sentence_for_context(context)
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
            answer_sentence = first_sentence(cleaned_answer)
            candidate_rank = (
                1 if is_informative_answer_sentence(answer_sentence) else 0,
                question_score,
                len(tokenize(cleaned_answer)),
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
