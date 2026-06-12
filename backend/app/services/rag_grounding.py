from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Generic, Protocol, Sequence, TypeVar


CONTEXT_FALLBACK_CHAR_LIMIT = 420
GROUNDING_SYSTEM_PROMPT = (
    "Answer only from the supplied evidence blocks. "
    "Prefer PDF evidence when it directly answers the question. "
    "Use web evidence only to fill gaps or answer current facts the PDFs do not cover. "
    "If the evidence is insufficient, say so plainly. "
    "Grounded prose matters more than repeating source markers. "
    "If you include a source marker, copy it exactly from the evidence blocks. "
    "Do not invent, repair, or paraphrase source markers."
)
COMPREHENSIVE_GROUNDING_SYSTEM_PROMPT = (
    "Answer only from the supplied evidence blocks. "
    "Provide a highly detailed, comprehensive, and exhaustive academic synthesis using the supplied evidence. "
    "Structure your response with clear paragraphs, headings, or bullet points if appropriate. "
    "Incorporate all relevant facts, clinical/technical details, examples, and distinctions present in the evidence. "
    "Prefer PDF evidence when it directly answers the question. "
    "Use web evidence only to fill gaps or answer current facts the PDFs do not cover. "
    "If the evidence is insufficient, say so plainly. "
    "Grounded prose matters more than repeating source markers. "
    "If you include a source marker, copy it exactly from the evidence blocks. "
    "Do not invent, repair, or paraphrase source markers."
)
UNGROUNDED_ANSWER_MESSAGE = "I couldn't ground a confident answer in the retrieved sources."
PREVIEW_NOISE_LINE_PATTERN = re.compile(r"(?im)^\s*(?:page\s+\d+\b.*|[^\n\r]*copyright\b.*)$")


class GroundingContext(Protocol):
    kind: str
    text: str


ContextT = TypeVar("ContextT", bound=GroundingContext)


@dataclass(frozen=True)
class GroundingFallbackAnswer(Generic[ContextT]):
    answer: str
    citation_contexts: tuple[ContextT, ...]
    generation_warning: str


def grounding_system_prompt() -> str:
    return GROUNDING_SYSTEM_PROMPT


def comprehensive_grounding_system_prompt() -> str:
    return COMPREHENSIVE_GROUNDING_SYSTEM_PROMPT


def no_context_message(*, web_search_enabled: bool, offline_warning: str | None) -> str:
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


def ungrounded_answer_message() -> str:
    return UNGROUNDED_ANSWER_MESSAGE


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    snippet = text[:max_chars].rstrip()
    last_space = snippet.rfind(" ")
    if last_space >= max_chars // 2:
        snippet = snippet[:last_space]
    return f"{snippet.rstrip(' ,;:')}..."


def normalize_context_text(text: str) -> str:
    cleaned = PREVIEW_NOISE_LINE_PATTERN.sub("", text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def clean_context_snippet(text: str, *, max_chars: int) -> str:
    normalized = normalize_context_text(text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return trim_text(normalized, max_chars) if normalized else ""


def compose_fallback_answer(
    contexts: Sequence[ContextT],
    *,
    generation_warning: str,
    extract_direct_qa_pair: Callable[[str], tuple[str, str] | None],
) -> GroundingFallbackAnswer[ContextT]:
    for context in contexts:
        if context.kind != "pdf":
            continue
        qa_pair = extract_direct_qa_pair(context.text)
        if qa_pair is None:
            continue
        _qa_question, qa_answer = qa_pair
        if qa_answer:
            return GroundingFallbackAnswer(
                answer=qa_answer,
                citation_contexts=(context,),
                generation_warning=generation_warning,
            )

    best_contexts = tuple(contexts[:2])
    fallback_passages = [
        clean_context_snippet(context.text, max_chars=CONTEXT_FALLBACK_CHAR_LIMIT)
        for context in best_contexts
    ]
    fallback_answer = "\n\n".join(
        passage
        for passage in fallback_passages
        if passage
    ).strip()
    if not fallback_answer:
        fallback_answer = ungrounded_answer_message()
    return GroundingFallbackAnswer(
        answer=fallback_answer,
        citation_contexts=best_contexts,
        generation_warning=generation_warning,
    )
