from __future__ import annotations

from typing import Sequence

from app.models.schemas import CitationPayload
from app.services.rag_answer_text import (
    CONCISE_ANSWER_PATTERN,
    DIRECT_QA_MATCH_THRESHOLD,
    ONE_SENTENCE_PATTERN,
    THREE_SENTENCE_PATTERN,
    TWO_SENTENCE_PATTERN,
    comparison_sentence_for_context,
    extract_direct_qa_pair,
    first_sentence,
    is_informative_answer_sentence,
    question_match_score,
    shape_shortcut_answer,
    tokenize,
)
from app.services.rag_citations import citation_from_context
from app.services.rag_grounding import (
    CONTEXT_FALLBACK_CHAR_LIMIT,
    clean_context_snippet,
    compose_fallback_answer,
)
from app.services.rag_types import FinalizedAnswer, RetrievedContext


def direct_comparison_shortcut(
    question: str,
    contexts: Sequence[RetrievedContext],
) -> tuple[str, list[CitationPayload]] | None:
    del question
    if len(contexts) < 2:
        return None

    comparison_sentences: list[str] = []
    citations: list[CitationPayload] = []
    for index, context in enumerate(contexts[:2]):
        sentence = comparison_sentence_for_context(context)
        if not sentence:
            return None
        if index == 1:
            sentence = (
                f"In contrast, {sentence[0].lower()}{sentence[1:]}"
                if len(sentence) > 1
                else f"In contrast, {sentence.lower()}"
            )
        comparison_sentences.append(sentence)
        citations.append(citation_from_context(context))

    answer = " ".join(comparison_sentences).strip()
    if not answer:
        return None
    return answer, citations


def direct_context_shortcut(
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


def fallback_finalized_answer(
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


def interactive_generation_options(
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


def reasoning_context_summary(contexts: list[RetrievedContext]) -> str:
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
