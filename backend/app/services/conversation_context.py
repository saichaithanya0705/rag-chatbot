from __future__ import annotations

import re

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
EXPLICIT_REFERENCE_PATTERN = re.compile(
    r"\b(it|its|they|them|their|that|those|these|this|former|latter|previous|earlier|above|below|same one)\b",
    re.IGNORECASE,
)
ELLIPTICAL_FOLLOW_UP_PATTERN = re.compile(
    r"^(?:why(?: is that)?|how so|go on|continue|more(?: details)?|details|examples?|shorter|briefly|what about|how about|summarize that|rephrase that)\b",
    re.IGNORECASE,
)


def looks_context_dependent(question: str) -> bool:
    normalized = " ".join(question.strip().split())
    if not normalized:
        return False

    if EXPLICIT_REFERENCE_PATTERN.search(normalized):
        return True

    token_count = len(TOKEN_PATTERN.findall(normalized.lower()))
    return token_count <= 6 and bool(ELLIPTICAL_FOLLOW_UP_PATTERN.search(normalized))
