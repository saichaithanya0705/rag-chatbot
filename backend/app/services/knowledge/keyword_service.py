from __future__ import annotations

from collections import Counter
import re
import unicodedata

ENGLISH_STOP_WORDS = frozenset({
    "a", "about", "above", "across", "after", "afterwards", "again", "against", "all", "almost",
    "alone", "along", "already", "also", "although", "always", "am", "among", "amongst", "amoungst",
    "amount", "an", "and", "another", "any", "anyhow", "anyone", "anything", "anyway", "anywhere",
    "are", "around", "as", "at", "back", "be", "became", "because", "become", "becomes",
    "becoming", "been", "before", "beforehand", "behind", "being", "below", "beside", "besides",
    "between", "beyond", "bill", "both", "bottom", "but", "by", "call", "can", "cannot",
    "cant", "co", "con", "could", "couldnt", "cry", "de", "describe", "detail", "do",
    "done", "down", "due", "during", "each", "eg", "eight", "either", "eleven", "else",
    "elsewhere", "empty", "enough", "etc", "even", "ever", "every", "everyone", "everything",
    "everywhere", "except", "few", "fifteen", "fifty", "fill", "find", "fire", "first", "five",
    "for", "former", "formerly", "forty", "found", "four", "from", "front", "full", "further",
    "get", "give", "go", "had", "has", "hasnt", "have", "he", "hence", "her", "here",
    "hereafter", "hereby", "herein", "hereupon", "hers", "herself", "him", "himself", "his",
    "how", "however", "hundred", "i", "ie", "if", "in", "inc", "indeed", "interest", "into",
    "is", "it", "its", "itself", "keep", "last", "latter", "latterly", "least", "less",
    "ltd", "made", "many", "may", "me", "meanwhile", "might", "mill", "mine", "more",
    "moreover", "most", "mostly", "move", "much", "must", "my", "myself", "name", "namely",
    "neither", "never", "nevertheless", "next", "nine", "no", "nobody", "none", "noone",
    "nor", "not", "nothing", "now", "nowhere", "of", "off", "often", "on", "once", "one",
    "only", "onto", "or", "other", "others", "otherwise", "our", "ours", "ourselves", "out",
    "over", "own", "part", "per", "perhaps", "please", "put", "rather", "re", "same",
    "see", "seem", "seemed", "seeming", "seems", "serious", "several", "she", "should",
    "show", "side", "since", "sincere", "six", "sixty", "so", "some", "somehow", "someone",
    "something", "sometime", "sometimes", "somewhere", "still", "such", "system", "take",
    "ten", "than", "that", "the", "their", "them", "themselves", "then", "thence", "there",
    "thereafter", "thereby", "therefore", "therein", "thereupon", "these", "they", "thick",
    "thin", "third", "this", "those", "though", "three", "through", "throughout", "thru",
    "thus", "to", "together", "too", "top", "toward", "towards", "twelve", "twenty", "two",
    "un", "under", "until", "up", "upon", "us", "very", "via", "was", "we", "well",
    "were", "what", "whatever", "when", "whence", "whenever", "where", "whereafter", "whereas",
    "whereby", "wherein", "whereupon", "wherever", "whether", "which", "while", "whither",
    "who", "whoever", "whole", "whom", "whose", "why", "will", "with", "within", "without",
    "would", "yet", "you", "your", "yours", "yourself", "yourselves"
})


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
