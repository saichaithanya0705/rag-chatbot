from __future__ import annotations

from collections.abc import Sequence

from app.services.conversation_context import looks_context_dependent
from app.services.ollama_client import OllamaClient


class QueryRewriteService:
    def __init__(self, *, ollama_client: OllamaClient) -> None:
        self._ollama_client = ollama_client

    async def rewrite_query(
        self,
        question: str,
        *,
        history_messages: Sequence[dict[str, str]] | None = None,
    ) -> str:
        cleaned_question = " ".join(question.strip().split())
        if not cleaned_question:
            return question

        if not history_messages or not looks_context_dependent(cleaned_question):
            return cleaned_question

        recent_history = list(history_messages or [])[-4:]
        history_block = "\n".join(
            f"{message.get('role', 'user')}: {message.get('content', '').strip()}"
            for message in recent_history
            if message.get("content", "").strip()
        )
        prompt = (
            "Rewrite the user's latest message into a standalone retrieval query for semantic search.\n"
            "Preserve named entities, dates, versions, and technical terms.\n"
            "Resolve follow-up references using the supplied conversation when needed.\n"
            "Reply with the rewritten query only.\n\n"
            f"Conversation:\n{history_block or '(none)'}\n\n"
            f"Latest user message:\n{cleaned_question}"
        )
        system_prompt = (
            "You rewrite follow-up questions for retrieval systems. "
            "Do not answer the question. "
            "Return exactly one concise standalone search query."
        )

        try:
            rewritten = await self._ollama_client.generate_answer(
                prompt=prompt,
                system_prompt=system_prompt,
                options={
                    "temperature": 0,
                    "num_predict": 48,
                    "stop": ["\n"],
                },
            )
        except Exception:
            return cleaned_question

        normalized = self._sanitize_query(rewritten.response)
        return normalized or cleaned_question

    @staticmethod
    def _sanitize_query(value: str) -> str:
        normalized = " ".join(value.replace("\n", " ").strip().strip("\"'").split())
        if not normalized:
            return ""

        if len(normalized) > 240:
            normalized = normalized[:240].rstrip()

        return normalized
