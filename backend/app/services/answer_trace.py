from __future__ import annotations

from app.models.schemas import AnswerTraceStepPayload, CitationPayload, ToolCallPayload


def build_answer_trace(
    *,
    pdf_context_count: int = 0,
    citations: list[CitationPayload] | None = None,
    cross_session_memory_used: int = 0,
    collection_id: str | None = None,
    collection_label: str | None = None,
    tool_call: ToolCallPayload | None = None,
    web_search_requested: bool = True,
    web_search_used: bool = False,
    offline_warning: str | None = None,
    generation_warning: str | None = None,
    response_mode: str = "grounded",
    conversation_detail: str | None = None,
) -> list[AnswerTraceStepPayload]:
    trace_steps: list[AnswerTraceStepPayload] = []
    citation_list = citations or []
    resolved_collection_label = collection_label or collection_id or "All PDFs"

    if response_mode == "conversation":
        return [
            AnswerTraceStepPayload(
                kind="conversation",
                label="Conversation",
                detail=conversation_detail
                or "Handled this as a conversational message, so retrieval and generation were skipped.",
            )
        ]

    trace_steps.append(
        AnswerTraceStepPayload(
            kind="scope",
            label="Scope",
            detail=(
                f"Scoped this answer to {resolved_collection_label}. "
                f"Live web lookup was {'enabled' if web_search_requested else 'off'} for this turn."
            ),
        )
    )

    if cross_session_memory_used:
        trace_steps.append(
            AnswerTraceStepPayload(
                kind="memory",
                label="Cross-session memory",
                detail=(
                    f"Reused relevant context from {cross_session_memory_used} earlier session"
                    f"{'' if cross_session_memory_used == 1 else 's'} in this local workspace. "
                    "Start a fresh chat if you want answers grounded only in the current thread."
                ),
            )
        )

    if pdf_context_count:
        trace_steps.append(
            AnswerTraceStepPayload(
                kind="retrieval",
                label="PDF retrieval",
                detail=(
                    f"Retrieved {pdf_context_count} PDF excerpt"
                    f"{'' if pdf_context_count == 1 else 's'} to ground the answer."
                ),
            )
        )

    if tool_call is not None:
        if web_search_used and citation_list:
            detail = "Supplemented the answer with live web pages that were fetched and read."
        elif web_search_used:
            detail = "Fetched live web pages, but the final answer could not be grounded confidently enough to cite them."
        elif offline_warning:
            detail = offline_warning
        else:
            detail = "Checked whether live web evidence was needed before answering."
        trace_steps.append(
            AnswerTraceStepPayload(
                kind="web",
                label="Web evidence",
                detail=detail,
            )
        )
    elif offline_warning:
        trace_steps.append(
            AnswerTraceStepPayload(
                kind="web",
                label="Web evidence",
                detail=offline_warning,
            )
        )

    if generation_warning:
        trace_steps.append(
            AnswerTraceStepPayload(
                kind="generation",
                label="Answer generation",
                detail=generation_warning,
            )
        )

    if citation_list:
        trace_steps.append(
            AnswerTraceStepPayload(
                kind="citations",
                label="Citations",
                detail=(
                    f"Grounded the answer in {len(citation_list)} cited source"
                    f"{'' if len(citation_list) == 1 else 's'}."
                ),
            )
        )

    return trace_steps
