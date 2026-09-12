from __future__ import annotations

import time
from typing import Protocol

from app.services.chat.message_intent import classify_message_intent
from app.services.providers.nvidia_client import NvidiaGenerationResult
from app.services.rag.rag_answer_text import extract_direct_qa_pair
from app.services.rag.rag_grounding import compose_fallback_answer, grounding_system_prompt
from app.services.rag.rag_prompting import build_prompt
from app.services.rag.rag_retrieval import rank_candidates_by_relevance
from app.services.rag.rag_service import RagService
from app.services.rag.rag_types import CandidateChunk, RetrievedContext
from quality_evals.core import EvalCase, EvalContext, EvalOutput


class GenerationClient(Protocol):
    async def generate_answer(self, **kwargs: object) -> NvidiaGenerationResult: ...


class _RecordedGenerationClient:
    def __init__(self, response: str) -> None:
        self._response = response

    async def generate_answer(self, **_kwargs: object) -> NvidiaGenerationResult:
        return NvidiaGenerationResult(response=self._response)


class _RecordedReranker:
    def __init__(self, scores: list[float]) -> None:
        self._scores = scores

    def score_pairs(self, _question: str, _passages: list[str]) -> list[float]:
        return list(self._scores)


async def run_target(
    case: EvalCase,
    *,
    live_client: GenerationClient | None = None,
) -> EvalOutput:
    started = time.perf_counter()
    if case.target == "fallback":
        result = compose_fallback_answer(
            case.contexts,
            question=case.question,
            generation_warning="evaluation fixture",
            extract_direct_qa_pair=extract_direct_qa_pair,
        )
        output = EvalOutput(
            answer=result.answer,
            citation_ids=tuple(context.id for context in result.citation_contexts),
        )
    elif case.target == "generation":
        output = await _run_generation(case, live_client=live_client)
    elif case.target == "intent":
        output = await _run_intent(case, live_client=live_client)
    elif case.target == "retrieval":
        output = _run_retrieval(case)
    else:  # pragma: no cover - dataset validation prevents this branch
        raise ValueError(f"unsupported evaluation target {case.target!r}")

    return EvalOutput(
        answer=output.answer,
        context_ids=output.context_ids,
        citation_ids=output.citation_ids,
        intent=output.intent,
        raw_output=output.raw_output,
        latency_ms=(time.perf_counter() - started) * 1000,
    )


async def _run_generation(
    case: EvalCase,
    *,
    live_client: GenerationClient | None,
) -> EvalOutput:
    contexts = [_retrieved_context(context) for context in case.contexts]
    if live_client is None:
        raw_output = case.recorded_output or ""
    else:
        result = await live_client.generate_answer(
            prompt=build_prompt(
                question=case.question,
                contexts=contexts,
                history_messages=case.history,
            ),
            system_prompt=grounding_system_prompt(),
            options={"temperature": 0, "num_predict": 800},
            include_thinking=False,
        )
        raw_output = str(result.response)

    finalized = RagService.finalize_streamed_answer(
        raw_output,
        contexts,
        question=case.question,
    )
    return EvalOutput(
        answer=finalized.answer,
        citation_ids=tuple(citation.id for citation in finalized.citations),
        raw_output=raw_output,
    )


async def _run_intent(
    case: EvalCase,
    *,
    live_client: GenerationClient | None,
) -> EvalOutput:
    client = live_client or _RecordedGenerationClient(case.recorded_output or "")
    result = await classify_message_intent(
        case.question,
        nvidia_client=client,
        history_messages=case.history,
        include_thinking=False,
    )
    return EvalOutput(intent=result.kind, raw_output=case.recorded_output)


def _run_retrieval(case: EvalCase) -> EvalOutput:
    ranked = rank_candidates_by_relevance(
        question=case.question,
        ordered_candidates=[_candidate(context, index=index) for index, context in enumerate(case.contexts)],
        reranker_service=_RecordedReranker(
            [float(context.rerank_score) for context in case.contexts]
        ),
    )
    return EvalOutput(context_ids=tuple(candidate.chunk_id for candidate in ranked))


def _retrieved_context(context: EvalContext) -> RetrievedContext:
    if context.kind == "web":
        label = f"[Web: {context.url}]"
    else:
        label = f"[SourceID: {context.id}]"
    return RetrievedContext(
        id=context.id,
        kind=context.kind,
        label=label,
        text=context.text,
        excerpt=context.text[:280],
        document_id=f"document-{context.id}" if context.kind == "pdf" else None,
        pdf_name=context.pdf_name or (f"{context.id}.pdf" if context.kind == "pdf" else None),
        page_number=context.page_number or (1 if context.kind == "pdf" else None),
        chunk_index=context.chunk_index if context.chunk_index is not None else (0 if context.kind == "pdf" else None),
        url=context.url,
        title=context.title,
    )


def _candidate(context: EvalContext, *, index: int) -> CandidateChunk:
    return CandidateChunk(
        chunk_id=context.id,
        collection_id="all_chunks",
        document_id=f"document-{context.id}",
        pdf_name=context.pdf_name or f"{context.id}.pdf",
        page_number=context.page_number or 1,
        chunk_index=context.chunk_index if context.chunk_index is not None else index,
        text=context.text,
        fused_score=1.0 / (index + 1),
    )
