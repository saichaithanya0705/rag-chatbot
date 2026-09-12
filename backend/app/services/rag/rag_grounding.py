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


# Conservative lexical evidence check for the deterministic fallback only. Semantic
# paraphrases remain supported by the separately validated extractive model.
QUESTION_STOP_WORDS = frozenset(
    "a an the is are was were be been being what which who when where why how "
    "do does did can could would should will please tell me about explain describe "
    "define give in of to for and or with this that it my pdf document documents "
    "information detail details briefly".split()
)


def evidence_overlap(question: str, text: str) -> float:
    terms = set(re.findall(r"[a-z0-9]+", question.lower())) - QUESTION_STOP_WORDS
    if not terms:
        return 0.0
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    return len(terms & words) / len(terms)


def compose_fallback_answer(
    contexts: Sequence[ContextT],
    *,
    question: str,
    generation_warning: str,
    extract_direct_qa_pair: Callable[[str], tuple[str, str] | None],
) -> GroundingFallbackAnswer[ContextT]:
    # Never copy the first retrieved chunk just because it exists. Select only
    # matching answers/sentences, including a short answer in a matching Q&A.
    for context in contexts:
        if context.kind != "pdf":
            continue
        qa_pair = extract_direct_qa_pair(context.text)
        if qa_pair is not None:
            qa_question, qa_answer = qa_pair
            if qa_answer.strip() and evidence_overlap(question, qa_question) >= 0.7:
                return GroundingFallbackAnswer(
                    answer=clean_context_snippet(qa_answer, max_chars=CONTEXT_FALLBACK_CHAR_LIMIT),
                    citation_contexts=(context,),
                    generation_warning=generation_warning,
                )

    passages: list[str] = []
    cited: list[ContextT] = []
    seen: set[str] = set()
    for context in contexts:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", normalize_context_text(context.text)):
            sentence = clean_context_snippet(sentence, max_chars=CONTEXT_FALLBACK_CHAR_LIMIT)
            if (
                not sentence
                or sentence.endswith("?")
                or evidence_overlap(question, sentence) < 0.7
                or sentence.casefold() in seen
            ):
                continue
            passages.append(sentence)
            seen.add(sentence.casefold())
            if context not in cited:
                cited.append(context)
            if len(passages) == 2:
                break
        if len(passages) == 2:
            break
    return GroundingFallbackAnswer(
        answer="\n\n".join(passages) if passages else ungrounded_answer_message(),
        citation_contexts=tuple(cited),
        generation_warning=generation_warning,
    )
