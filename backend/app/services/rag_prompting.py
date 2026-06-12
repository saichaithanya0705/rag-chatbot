from __future__ import annotations

import re
from typing import Sequence

from app.services.conversation_context import looks_context_dependent
from app.services.rag_answer_text import tokenize
from app.services.rag_grounding import trim_text
from app.services.rag_types import RetrievedContext


PROMPT_HISTORY_USER_MESSAGE_LIMIT = 2
PROMPT_PDF_CONTEXT_LIMIT = 3
PROMPT_WEB_CONTEXT_LIMIT = 2
PROMPT_PDF_CONTEXT_CHAR_LIMIT = 1200
PROMPT_WEB_CONTEXT_CHAR_LIMIT = 1000


def select_contexts(
    pdf_contexts: list[RetrievedContext],
    web_contexts: list[RetrievedContext],
    *,
    top_k: int,
) -> list[RetrievedContext]:
    pdf_limit = 12 if top_k >= 10 else (6 if top_k >= 5 else PROMPT_PDF_CONTEXT_LIMIT)
    web_limit = 6 if top_k >= 10 else (3 if top_k >= 5 else PROMPT_WEB_CONTEXT_LIMIT)
    selected_pdf_contexts = pdf_contexts[: min(pdf_limit, top_k)]
    selected_web_contexts = web_contexts[: min(web_limit, top_k)]
    return [*selected_pdf_contexts, *selected_web_contexts]


def build_prompt(
    *,
    question: str,
    contexts: list[RetrievedContext],
    history_messages: Sequence[dict[str, str]],
    response_length: str = "standard",
) -> str:
    prompt_sections = [
        "Use only the retrieved evidence below to answer the user's question.",
        "Each evidence block starts with an exact source marker. Reuse a marker verbatim only when you need to cite directly.",
    ]
    pdf_contexts = [context for context in contexts if context.kind == "pdf"]
    web_contexts = [context for context in contexts if context.kind == "web"]
    user_history = [message for message in history_messages if message.get("role") == "user"]

    if pdf_contexts:
        prompt_sections.append(
            "PDF context:\n"
            + "\n\n".join(
                render_context_for_prompt(question=question, context=context, response_length=response_length)
                for context in pdf_contexts
            )
        )

    if web_contexts:
        prompt_sections.append(
            "Web search context:\n"
            + "\n\n".join(
                render_context_for_prompt(question=question, context=context, response_length=response_length)
                for context in web_contexts
            )
        )

    if user_history and looks_context_dependent(question):
        rendered_history = "\n".join(
            f"User: {message['content']}"
            for message in user_history[-PROMPT_HISTORY_USER_MESSAGE_LIMIT:]
        )
        prompt_sections.append(
            "Recent user messages for conversational context only (not evidence):\n"
            f"{rendered_history}"
        )

    prompt_sections.append(
        f"Question: {question}\n\n"
        "Answer in plain prose. Prefer one to three short paragraphs unless the user asks for a list or more detail. "
        "If the user asks for a specific sentence count or a brief answer, honor that strictly. "
        "Keep the answer tightly grounded in the evidence. If you include a source marker, copy it exactly from the context."
    )
    return "\n\n".join(prompt_sections)


def render_context_for_prompt(
    *,
    question: str,
    context: RetrievedContext,
    response_length: str = "standard",
) -> str:
    if response_length == "comprehensive":
        max_chars = 3000 if context.kind == "pdf" else 2000
    else:
        max_chars = (
            PROMPT_WEB_CONTEXT_CHAR_LIMIT
            if context.kind == "web"
            else PROMPT_PDF_CONTEXT_CHAR_LIMIT
        )
    return (
        f"{context.label}\n"
        f"{focus_context_text(question=question, text=context.text, max_chars=max_chars)}"
    )


def focus_context_text(
    *,
    question: str,
    text: str,
    max_chars: int,
) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= max_chars:
        return normalized

    query_tokens = {
        token
        for token in tokenize(question)
        if len(token) > 2
    }
    if not query_tokens:
        return trim_text(normalized, max_chars)

    stride = max(120, max_chars // 3)
    max_start = max(len(normalized) - max_chars, 0)
    window_starts = list(range(0, max_start + 1, stride)) or [0]
    if window_starts[-1] != max_start:
        window_starts.append(max_start)

    best_start = 0
    best_score = -1
    for start in window_starts:
        candidate = normalized[start : start + max_chars]
        score = len(query_tokens & set(tokenize(candidate)))
        if score > best_score:
            best_score = score
            best_start = start

    return trim_text_window(normalized, best_start, max_chars)


def trim_text_window(text: str, start: int, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    start = min(max(start, 0), max(len(text) - max_chars, 0))
    end = min(start + max_chars, len(text))
    snippet = text[start:end]

    if start > 0 and not text[start - 1].isspace():
        first_space = snippet.find(" ")
        if 0 <= first_space < max_chars // 3:
            snippet = snippet[first_space + 1 :]
    if start > 0:
        snippet = f"...{snippet.lstrip()}"

    if end < len(text):
        last_space = snippet.rfind(" ")
        if last_space >= len(snippet) // 2:
            snippet = snippet[:last_space]
        snippet = f"{snippet.rstrip(' ,;:')}..."

    return snippet
