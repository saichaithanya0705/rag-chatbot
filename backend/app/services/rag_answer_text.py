from __future__ import annotations

import re

from app.models.schemas import CitationPayload
from app.services.rag_citations import citation_from_context
from app.services.rag_grounding import (
    CONTEXT_FALLBACK_CHAR_LIMIT,
    clean_context_snippet,
    normalize_context_text,
)
from app.services.rag_types import RetrievedContext


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
DIRECT_QA_PATTERN = re.compile(
    r"^\s*(?:question:\s*(?P<question>.+?)\n+\s*answer:\s*(?P<answer>.+)|(?P<numbered_question>\d{1,3}[.)]\s*.+?)\n+\n*(?P<numbered_answer>.+))$",
    re.IGNORECASE | re.DOTALL,
)
ONE_SENTENCE_PATTERN = re.compile(r"\b(?:one|1)\s+(?:short\s+)?sentence\b", re.IGNORECASE)
TWO_SENTENCE_PATTERN = re.compile(r"\b(?:two|2)\s+(?:short\s+)?sentences\b", re.IGNORECASE)
THREE_SENTENCE_PATTERN = re.compile(r"\b(?:three|3)\s+(?:short\s+)?sentences\b", re.IGNORECASE)
CONCISE_ANSWER_PATTERN = re.compile(
    r"\b(?:brief(?:ly)?|concise(?:ly)?|short(?:er)?|summari[sz]e|summary|in brief|quick(?:ly)?)\b",
    re.IGNORECASE,
)
DIRECT_QA_MIN_TOKEN_COUNT = 4


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def strip_thinking_blocks(answer: str) -> str:
    without_closed_blocks = THINK_BLOCK_PATTERN.sub("", answer)
    return OPEN_THINK_BLOCK_PATTERN.sub("", without_closed_blocks).strip()


def strip_citation_markers(answer: str) -> str:
    stripped = PDF_CITATION_PATTERN.sub("", answer)
    stripped = LEGACY_PDF_CITATION_PATTERN.sub("", stripped)
    stripped = WEB_CITATION_PATTERN.sub("", stripped)
    return re.sub(r"\s{2,}", " ", stripped)


def normalize_answer_text(answer: str) -> str:
    normalized = re.sub(r"\s+([,.;:!?])", r"\1", answer)
    normalized = re.sub(r"([(\[])\s+", r"\1", normalized)
    normalized = re.sub(r"\s+([)\]])", r"\1", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    if normalized.endswith('"') and not normalized.startswith('"'):
        normalized = normalized[:-1].rstrip()
    if normalized.endswith("'") and not normalized.startswith("'"):
        normalized = normalized[:-1].rstrip()
    return normalized


def clean_model_thinking_summary(summary: str) -> str | None:
    cleaned = strip_thinking_blocks(summary)
    cleaned = re.sub(r"\[SourceID:[^\]]+\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[Web:[^\]]+\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = MODEL_THINKING_SENSITIVE_LINE_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return None
    if "reasoning summary" not in cleaned[:80].lower():
        cleaned = f"Reasoning summary\n\n{cleaned}"
    return cleaned[:1400].rstrip()


def extract_direct_qa_pair(text: str) -> tuple[str, str] | None:
    normalized_text = normalize_context_text(text)
    match = DIRECT_QA_PATTERN.match(normalized_text)
    if not match:
        return None

    if match.group("question") and match.group("answer"):
        question = clean_context_snippet(match.group("question"), max_chars=CONTEXT_FALLBACK_CHAR_LIMIT)
        answer = clean_qa_answer_text(match.group("answer"))
        return (question, answer) if question and answer else None

    numbered_text = re.sub(r"^\s*\d{1,3}[.)]\s*", "", normalized_text)
    question_boundaries = [
        question_mark.end()
        for question_mark in re.finditer(r"\?", numbered_text[: CONTEXT_FALLBACK_CHAR_LIMIT * 2])
    ]
    for boundary in reversed(question_boundaries):
        numbered_question = clean_context_snippet(
            numbered_text[:boundary],
            max_chars=CONTEXT_FALLBACK_CHAR_LIMIT,
        )
        numbered_answer = clean_qa_answer_text(numbered_text[boundary:])
        if numbered_question and numbered_answer:
            return numbered_question, numbered_answer

    numbered_question = clean_context_snippet(
        re.sub(r"^\d{1,3}[.)]\s*", "", match.group("numbered_question") or ""),
        max_chars=CONTEXT_FALLBACK_CHAR_LIMIT,
    )
    numbered_answer = clean_qa_answer_text(match.group("numbered_answer") or "")
    return (numbered_question, numbered_answer) if numbered_question and numbered_answer else None


def clean_qa_answer_text(text: str) -> str:
    cleaned = re.sub(r"^\s*answer:\s*", "", text or "", flags=re.IGNORECASE).strip()
    repeated_question_match = re.match(
        r"^(?:question:\s*|(?:\d{1,3}[.)]\s*))?(?P<question>.+?\?)\s*(?P<rest>.+)$",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if repeated_question_match and repeated_question_match.group("rest").strip():
        cleaned = repeated_question_match.group("rest").strip()
    return clean_context_snippet(cleaned, max_chars=CONTEXT_FALLBACK_CHAR_LIMIT * 2)


def question_match_score(user_question: str, candidate_question: str) -> float:
    user_tokens = {
        token
        for token in tokenize(normalize_question_for_matching(user_question))
        if len(token) > 2
    }
    candidate_tokens = {
        token
        for token in tokenize(candidate_question)
        if len(token) > 2
    }
    if len(user_tokens) < DIRECT_QA_MIN_TOKEN_COUNT or len(candidate_tokens) < DIRECT_QA_MIN_TOKEN_COUNT:
        return 0.0
    overlap = user_tokens & candidate_tokens
    if not overlap:
        return 0.0
    return len(overlap) / max(1, min(len(user_tokens), len(candidate_tokens)))


def normalize_question_for_matching(question: str) -> str:
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


def shape_shortcut_answer(question: str, answer: str) -> str:
    normalized_answer = normalize_answer_text(answer)
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


def claim_window(answer: str, marker_start: int) -> str:
    window_start = max(0, marker_start - 260)
    prefix = answer[window_start:marker_start]
    boundary = max(prefix.rfind("."), prefix.rfind("!"), prefix.rfind("?"), prefix.rfind("\n"))
    if boundary >= 0:
        prefix = prefix[boundary + 1 :]
    return prefix.strip()


def substantive_segments(answer: str) -> list[str]:
    segments: list[str] = []
    for segment in re.split(r"(\n\s*\n+)", answer.strip()):
        if not segment or segment.isspace():
            continue
        if not TOKEN_PATTERN.search(segment):
            continue
        segments.append(segment.strip())
    return segments


def best_page_context(
    answer: str,
    marker_start: int,
    page_contexts: list[RetrievedContext],
) -> RetrievedContext | None:
    if not page_contexts:
        return None
    if len(page_contexts) == 1:
        return page_contexts[0]

    claim_tokens = set(tokenize(claim_window(answer, marker_start)))
    if not claim_tokens:
        return page_contexts[0]

    return max(
        page_contexts,
        key=lambda context: len(claim_tokens & set(tokenize(context.text))),
    )


def best_context_for_segment(
    segment: str,
    contexts: list[RetrievedContext],
) -> RetrievedContext | None:
    segment_tokens = set(tokenize(segment))
    if len(segment_tokens) < 2:
        return None

    best_context: RetrievedContext | None = None
    best_score = 0.0
    best_overlap = 0
    for context in contexts:
        context_tokens = set(tokenize(context.text))
        overlap = segment_tokens & context_tokens
        if not overlap:
            continue

        score = len(overlap) / max(len(segment_tokens), 1)
        if context.title:
            title_tokens = set(tokenize(context.title))
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


def has_uncited_substantive_segments(
    answer: str,
    contexts: list[RetrievedContext],
) -> bool:
    for segment in substantive_segments(answer):
        if (
            PDF_CITATION_PATTERN.search(segment)
            or LEGACY_PDF_CITATION_PATTERN.search(segment)
            or WEB_CITATION_PATTERN.search(segment)
        ):
            continue
        if best_context_for_segment(segment, contexts) is None:
            return True
    return False


def references_unknown_sources(answer: str, contexts: list[RetrievedContext]) -> bool:
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


def derive_citations_from_answer(
    answer: str,
    contexts: list[RetrievedContext],
) -> list[CitationPayload]:
    citations_by_id: dict[str, CitationPayload] = {}
    for segment in substantive_segments(answer):
        context = best_context_for_segment(segment, contexts)
        if context is None:
            return []
        citations_by_id[context.id] = citation_from_context(context)
    return list(citations_by_id.values())
