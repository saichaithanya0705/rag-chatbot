from __future__ import annotations

from collections import Counter
import re
import unicodedata

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS


TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]{1,}")
GENERIC_NOISE_TOKENS = {
    "click",
    "contents",
    "continued",
    "copyright",
    "free",
    "interviewbit",
    "live",
    "masterclass",
    "masterclasses",
    "page",
    "register",
    "version",
    "view",
}


class KeywordService:
    def __init__(
        self,
        *,
        base_url: str,  # noqa: ARG002
        embed_model: str,  # noqa: ARG002
        chat_model: str,  # noqa: ARG002
        top_n: int = 5,
        llm_tag_count: int = 3,  # noqa: ARG002
        llm_concurrency: int = 4,  # noqa: ARG002
    ) -> None:
        self._top_n = max(1, top_n)

    async def extract_keywords(self, texts: list[str]) -> list[list[str]]:
        return [self._extract_keywords_fast(text) for text in texts]

    async def aclose(self) -> None:
        return None

    def _extract_keywords_fast(self, text: str) -> list[str]:
        tokens = self._normalized_tokens(text)
        if not tokens:
            return []

        unigram_counts = Counter(tokens)
        bigram_counts = Counter(
            f"{left} {right}"
            for left, right in zip(tokens, tokens[1:], strict=False)
            if left != right
        )

        ranked_phrases: list[str] = []
        seen = set()

        for phrase, count in sorted(
            bigram_counts.items(),
            key=lambda item: (-item[1], -len(item[0]), item[0]),
        ):
            if count < 2 and len(bigram_counts) > self._top_n:
                continue
            if phrase in seen:
                continue
            ranked_phrases.append(phrase)
            seen.add(phrase)
            if len(ranked_phrases) >= self._top_n:
                return ranked_phrases

        for phrase, _count in sorted(
            unigram_counts.items(),
            key=lambda item: (-item[1], -len(item[0]), item[0]),
        ):
            if phrase in seen:
                continue
            ranked_phrases.append(phrase)
            seen.add(phrase)
            if len(ranked_phrases) >= self._top_n:
                break

        return ranked_phrases

    @staticmethod
    def _normalized_tokens(text: str) -> list[str]:
        normalized_text = unicodedata.normalize("NFKC", text.lower())
        raw_tokens = TOKEN_PATTERN.findall(normalized_text)
        normalized: list[str] = []
        for token in raw_tokens:
            candidate = token.strip("._-/")
            if len(candidate) < 3:
                continue
            if candidate in ENGLISH_STOP_WORDS:
                continue
            if candidate in GENERIC_NOISE_TOKENS:
                continue
            if candidate.isdigit():
                continue
            normalized.append(candidate)
        return normalized
