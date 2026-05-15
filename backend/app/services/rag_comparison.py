from __future__ import annotations

import re

from app.services.rag_answer_text import extract_direct_qa_pair, tokenize
from app.services.rag_types import CandidateChunk


COMPARISON_QUERY_PATTERN = re.compile(
    r"\b(compare|comparison|contrast|difference(?:s)?|differentiate|vs\.?|versus)\b",
    re.IGNORECASE,
)
BETWEEN_COMPARISON_PATTERN = re.compile(
    r"\bbetween\s+(?P<left>.+?)\s+\band\b\s+(?P<right>.+)$",
    re.IGNORECASE,
)
COMPARISON_SPLIT_PATTERN = re.compile(r"\b(?:and|vs\.?|versus)\b", re.IGNORECASE)
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
COMPARISON_STOP_TOKENS = frozenset({"a", "an", "and", "or", "the"})


def comparison_subqueries(question: str) -> list[str]:
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
    raw_parts = (
        [between_match.group("left"), between_match.group("right")]
        if between_match
        else COMPARISON_SPLIT_PATTERN.split(normalized)
    )

    subqueries: list[str] = []
    for part in raw_parts:
        cleaned = re.sub(
            r"^(?:compare|comparison|contrast|difference(?:s)?(?: between)?|differentiate)\s+",
            "",
            part.strip(),
            flags=re.IGNORECASE,
        )
        cleaned = cleaned.strip(" ?.,:;")
        if len(tokenize(cleaned)) < 2:
            continue
        if cleaned.lower() == question.strip().lower():
            continue
        subqueries.append(cleaned)

    return list(dict.fromkeys(subqueries))


def comparison_search_query(subquery: str) -> str:
    tokens = [token for token in tokenize(subquery) if len(token) > 2]
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


def comparison_question_score(subquery: str, candidate: CandidateChunk) -> float:
    qa_pair = extract_direct_qa_pair(candidate.text)
    candidate_question = qa_pair[0] if qa_pair is not None else candidate.text
    query_tokens = comparison_match_tokens(subquery, drop_generic=True)
    candidate_tokens = comparison_match_tokens(candidate_question)
    if not query_tokens or not candidate_tokens:
        return 0.0

    overlap = query_tokens & candidate_tokens
    if not overlap:
        return 0.0

    recall = len(overlap) / len(query_tokens)
    precision = len(overlap) / len(candidate_tokens)
    return (2 * recall * precision) / (recall + precision)


def comparison_match_tokens(
    text: str,
    *,
    drop_generic: bool = False,
) -> set[str]:
    tokens = [
        token
        for token in tokenize(text)
        if len(token) > 2 and token not in COMPARISON_STOP_TOKENS
    ]
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
        normalized_tokens.update(comparison_token_variants(token))
    return normalized_tokens


def comparison_token_variants(token: str) -> set[str]:
    variants = {token}
    if len(token) > 4 and token.endswith("ies"):
        variants.add(f"{token[:-3]}y")
    has_special_es_plural = len(token) > 4 and re.search(r"(?:ch|sh|x|z|s)es$", token)
    if has_special_es_plural:
        variants.add(token[:-2])
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss") and not has_special_es_plural:
        variants.add(token[:-1])
    return {variant for variant in variants if len(variant) > 2}
