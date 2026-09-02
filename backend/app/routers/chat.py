from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.dependencies import get_container, get_user_id
from app.models.schemas import ChatRequest, ChatResponse
from app.services.answer_trace import build_answer_trace

if TYPE_CHECKING:
    from app.services.container import ServiceContainer
    from app.services.rag_types import FinalizedAnswer, PreparedAnswer

router = APIRouter(prefix="/chat", tags=["chat"])
KEEPALIVE_INTERVAL_SECONDS = 8.0
CHAT_RATE_LIMIT_DETAIL = "This portfolio demo has a strict chat limit. Please wait before sending another message."
logger = logging.getLogger(__name__)

# Per-session streaming lock: prevents two concurrent streams for the same session
# from queuing duplicate LLM calls for the same session.
_session_stream_locks: dict[str, asyncio.Lock] = {}


def _resolve_collection_label(
    container: ServiceContainer,
    *,
    collection_id: str,
    user_id: str,
) -> str:
    if collection_id == "all-pdfs":
        return "All PDFs"

    for topic in container.topic_index_service.list_topics(user_id=user_id):
        if topic.id == collection_id:
            return topic.label
    return collection_id


def _topic_exists(
    container: ServiceContainer,
    *,
    collection_id: str,
    user_id: str,
) -> bool:
    if collection_id == "all-pdfs":
        return True
    return any(topic.id == collection_id for topic in container.topic_index_service.list_topics(user_id=user_id))


def _client_rate_limit_id(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        first_forwarded_hop = forwarded_for.split(",", maxsplit=1)[0].strip()
        if first_forwarded_hop:
            return first_forwarded_hop

    for header_name in ("cf-connecting-ip", "x-real-ip"):
        header_value = request.headers.get(header_name, "").strip()
        if header_value:
            return header_value

    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _enforce_chat_rate_limit(
    *,
    container: ServiceContainer,
    request: Request,
    user_id: str,
) -> None:
    decision = container.chat_rate_limiter.check_and_record(
        user_id=user_id,
        client_id=_client_rate_limit_id(request),
    )
    if decision.allowed:
        return

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=CHAT_RATE_LIMIT_DETAIL,
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


@router.post("/query", response_model=ChatResponse)
async def query_chat(
    request: ChatRequest,
    http_request: Request,
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> ChatResponse:
    thinking_enabled = bool(request.thinking_enabled)
    try:
        _enforce_chat_rate_limit(
            container=container,
            request=http_request,
            user_id=user_id,
        )
        if not _topic_exists(container, collection_id=request.collection_id, user_id=user_id):
            raise HTTPException(
                status_code=409,
                detail="That topic scope is no longer available. Refresh topics and choose a current scope.",
            )
        collection_label = _resolve_collection_label(
            container,
            collection_id=request.collection_id,
            user_id=user_id,
        )
        if request.session_id:
            await asyncio.to_thread(
                container.history_service.ensure_session,
                request.session_id,
                request.collection_id,
                user_id=user_id,
            )
        history_messages, cross_session_memory_used = await container.history_service.get_hybrid_memory(
            question=request.message,
            session_id=request.session_id,
            collection_id=request.collection_id,
            nvidia_client=container.nvidia_client,
            user_id=user_id,
        )
        (
            answer,
            citations,
            tool_call,
            web_search_used,
            offline_warning,
            cross_session_memory_used,
            model_thinking,
            generation_warning,
            response_mode,
            trace_detail,
        ) = await container.rag_service.answer_question(
            request.message,
            collection_id=request.collection_id,
            history_messages=history_messages,
            cross_session_turn_count=cross_session_memory_used,
            web_search_enabled=request.web_search_enabled,
            thinking_enabled=thinking_enabled,
            response_length=request.response_length,
            images=request.images,
            user_id=user_id,
        )
        answer_trace = build_answer_trace(
            pdf_context_count=sum(1 for citation in citations if citation.kind == "pdf"),
            citations=citations,
            cross_session_memory_used=cross_session_memory_used,
            collection_id=request.collection_id,
            collection_label=collection_label,
            tool_call=tool_call,
            web_search_requested=request.web_search_enabled,
            web_search_used=web_search_used,
            offline_warning=offline_warning,
            generation_warning=generation_warning,
            response_mode=response_mode,
            conversation_detail=trace_detail,
        )
        session_warning: str | None = None
        recorded_thinking_requested = thinking_enabled

        if request.session_id:
            try:
                await container.history_service.save_turn(
                    session_id=request.session_id,
                    collection_id=request.collection_id,
                    collection_label=collection_label,
                    user_content=request.message,
                    assistant_content=answer,
                    citations=citations,
                    answer_trace=[step.model_dump(by_alias=True) for step in answer_trace],
                    tool_call=tool_call,
                    web_search_requested=request.web_search_enabled,
                    web_search_used=web_search_used,
                    offline_warning=offline_warning,
                    model_thinking=model_thinking,
                    thinking_requested=recorded_thinking_requested,
                    cross_session_memory_used=cross_session_memory_used,
                    nvidia_client=container.nvidia_client,
                    user_id=user_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Chat answer for session %s could not be persisted.", request.session_id)
                session_warning = (
                    "Answered successfully, but this turn could not be saved to session history."
                )
            else:
                if container.history_service.should_generate_title(request.session_id, user_id=user_id):
                    asyncio.create_task(
                        container.history_service.generate_title(
                            request.session_id,
                            request.message,
                            container.nvidia_client,
                            user_id=user_id,
                        )
                    )
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001
        logger.exception("Chat query failed for collection %s", request.collection_id)
        raise HTTPException(status_code=500, detail="Chat request failed.") from error

    return ChatResponse(
        answer=answer,
        citations=citations,
        answerTrace=answer_trace,
        collection_id=request.collection_id,
        collection_label=collection_label,
        tool_call=tool_call,
        web_search_requested=request.web_search_enabled,
        web_search_used=web_search_used,
        offline_warning=offline_warning,
        cross_session_memory_used=cross_session_memory_used,
        modelThinking=model_thinking,
        thinkingRequested=recorded_thinking_requested,
        sessionWarning=session_warning,
        session_title=None,
    )


@router.post("/stream")
async def stream_chat(
    request: ChatRequest,
    http_request: Request,
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> StreamingResponse:
    thinking_enabled = bool(request.thinking_enabled)
    _enforce_chat_rate_limit(
        container=container,
        request=http_request,
        user_id=user_id,
    )
    if not _topic_exists(container, collection_id=request.collection_id, user_id=user_id):
        raise HTTPException(
            status_code=409,
            detail="That topic scope is no longer available. Refresh topics and choose a current scope.",
        )
    collection_label = _resolve_collection_label(
        container,
        collection_id=request.collection_id,
        user_id=user_id,
    )
    if request.session_id:
        try:
            await asyncio.to_thread(
                container.history_service.ensure_session,
                request.session_id,
                request.collection_id,
                user_id=user_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    # Acquire or create a per-session lock to prevent concurrent streams
    session_lock_key = f"{user_id}:{request.session_id or '__no_session__'}"
    if session_lock_key not in _session_stream_locks:
        _session_stream_locks[session_lock_key] = asyncio.Lock()
    session_lock = _session_stream_locks[session_lock_key]

    if session_lock.locked():
        raise HTTPException(
            status_code=429,
            detail="A response is already being generated for this session. Please wait for it to finish.",
        )

    async def event_stream():
        history_task: asyncio.Task | None = None
        prepared_task: asyncio.Task | None = None
        generation_task: asyncio.Task | None = None
        request_started_at = asyncio.get_running_loop().time()

        async with session_lock:
            try:
                yield _format_sse(
                    {
                        "type": "status",
                        "stage": "preparing",
                        "message": "Gathering retrieval context.",
                    }
                )

                history_task = asyncio.create_task(
                    container.history_service.get_hybrid_memory(
                        question=request.message,
                        session_id=request.session_id,
                        collection_id=request.collection_id,
                        nvidia_client=container.nvidia_client,
                        user_id=user_id,
                    )
                )
                async for heartbeat in _wait_with_keepalive(history_task, stage="history"):
                    if await http_request.is_disconnected():
                        raise asyncio.CancelledError
                    yield heartbeat
                history_messages, cross_session_memory_used = history_task.result()
                logger.info(
                    "Chat stream history ready for session %s in %.2fs.",
                    request.session_id,
                    asyncio.get_running_loop().time() - request_started_at,
                )

                prepared_task = asyncio.create_task(
                    container.rag_service.prepare_answer(
                        request.message,
                        collection_id=request.collection_id,
                        history_messages=history_messages,
                        cross_session_turn_count=cross_session_memory_used,
                        web_search_enabled=request.web_search_enabled,
                        thinking_enabled=thinking_enabled,
                        response_length=request.response_length,
                        images=request.images,
                        user_id=user_id,
                    )
                )
                async for heartbeat in _wait_with_keepalive(prepared_task, stage="retrieval"):
                    if await http_request.is_disconnected():
                        raise asyncio.CancelledError
                    yield heartbeat
                prepared = prepared_task.result()
                logger.info(
                    "Chat stream retrieval ready for session %s in %.2fs.",
                    request.session_id,
                    asyncio.get_running_loop().time() - request_started_at,
                )

                if prepared.tool_call is not None:
                    yield _format_sse(
                        {
                            "type": "tool",
                            "toolCall": prepared.tool_call.model_dump(by_alias=True),
                            "offlineWarning": prepared.offline_warning,
                        }
                    )

                if prepared.shortcut_answer is not None:
                    answer_trace = build_answer_trace(
                        pdf_context_count=sum(1 for context in prepared.contexts if context.kind == "pdf"),
                        citations=prepared.shortcut_citations,
                        cross_session_memory_used=prepared.cross_session_turn_count,
                        collection_id=request.collection_id,
                        collection_label=collection_label,
                        tool_call=prepared.tool_call,
                        web_search_requested=request.web_search_enabled,
                        web_search_used=prepared.web_search_used,
                        offline_warning=prepared.offline_warning,
                        generation_warning=None,
                        response_mode=prepared.response_mode,
                        conversation_detail=prepared.trace_detail,
                    )
                    session_warning: str | None = None
                    model_thinking = await container.rag_service.summarize_model_thinking(
                        prepared.reasoning_segments,
                        question=prepared.question,
                        answer=prepared.shortcut_answer,
                        contexts=prepared.contexts,
                    ) if thinking_enabled else None
                    recorded_thinking_requested = thinking_enabled
                    if request.session_id:
                        try:
                            await container.history_service.save_turn(
                                session_id=request.session_id,
                                collection_id=request.collection_id,
                                collection_label=collection_label,
                                user_content=request.message,
                                assistant_content=prepared.shortcut_answer,
                                citations=prepared.shortcut_citations,
                                answer_trace=[step.model_dump(by_alias=True) for step in answer_trace],
                                tool_call=prepared.tool_call,
                                web_search_requested=request.web_search_enabled,
                                web_search_used=prepared.web_search_used,
                                offline_warning=prepared.offline_warning,
                                model_thinking=model_thinking,
                                thinking_requested=recorded_thinking_requested,
                                cross_session_memory_used=prepared.cross_session_turn_count,
                                nvidia_client=container.nvidia_client,
                                user_id=user_id,
                            )
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                "Shortcut chat answer for session %s could not be persisted.",
                                request.session_id,
                            )
                            session_warning = (
                                "Answered successfully, but this turn could not be saved to session history."
                            )
                        else:
                            if container.history_service.should_generate_title(request.session_id, user_id=user_id):
                                asyncio.create_task(
                                    container.history_service.generate_title(
                                        request.session_id,
                                        request.message,
                                        container.nvidia_client,
                                        user_id=user_id,
                                    )
                                )
                    yield _format_sse(
                        {
                            "type": "done",
                            "answer": prepared.shortcut_answer,
                            "citations": [
                                citation.model_dump(by_alias=True) for citation in prepared.shortcut_citations
                            ],
                            "answerTrace": [step.model_dump(by_alias=True) for step in answer_trace],
                            "collectionId": request.collection_id,
                            "collectionLabel": collection_label,
                            "toolCall": (
                                prepared.tool_call.model_dump(by_alias=True)
                                if prepared.tool_call is not None
                                else None
                            ),
                            "webSearchRequested": request.web_search_enabled,
                            "webSearchUsed": prepared.web_search_used,
                            "offlineWarning": prepared.offline_warning,
                            "crossSessionMemoryUsed": prepared.cross_session_turn_count,
                            "modelThinking": model_thinking,
                            "thinkingRequested": recorded_thinking_requested,
                            "sessionWarning": session_warning,
                        }
                    )
                    return

                generation_task = asyncio.create_task(
                    _stream_finalized_answer(
                        container=container,
                        prepared=prepared,
                        thinking_enabled=thinking_enabled,
                        http_request=http_request,
                    )
                )
                yield _format_sse(
                    {
                        "type": "status",
                        "stage": "answering",
                        "message": "Generating the grounded answer.",
                    }
                )
                async for heartbeat in _wait_with_keepalive(generation_task, stage="answering"):
                    if await http_request.is_disconnected():
                        raise asyncio.CancelledError
                    yield heartbeat

                finalized = await generation_task
                logger.info(
                    "Chat stream answer ready for session %s in %.2fs.",
                    request.session_id,
                    asyncio.get_running_loop().time() - request_started_at,
                )
                answer = finalized.answer
                citations = finalized.citations
                model_thinking = finalized.model_thinking
                answer_trace = build_answer_trace(
                    pdf_context_count=sum(1 for context in prepared.contexts if context.kind == "pdf"),
                    citations=citations,
                    cross_session_memory_used=prepared.cross_session_turn_count,
                    collection_id=request.collection_id,
                    collection_label=collection_label,
                    tool_call=prepared.tool_call,
                    web_search_requested=request.web_search_enabled,
                    web_search_used=prepared.web_search_used,
                    offline_warning=prepared.offline_warning,
                    generation_warning=finalized.generation_warning,
                    response_mode=prepared.response_mode,
                    conversation_detail=prepared.trace_detail,
                )
                session_warning: str | None = None
                recorded_thinking_requested = thinking_enabled
                if request.session_id:
                    try:
                        await container.history_service.save_turn(
                            session_id=request.session_id,
                            collection_id=request.collection_id,
                            collection_label=collection_label,
                            user_content=request.message,
                            assistant_content=answer,
                            citations=citations,
                            answer_trace=[step.model_dump(by_alias=True) for step in answer_trace],
                            tool_call=prepared.tool_call,
                            web_search_requested=request.web_search_enabled,
                            web_search_used=prepared.web_search_used,
                            offline_warning=prepared.offline_warning,
                            model_thinking=model_thinking,
                            thinking_requested=recorded_thinking_requested,
                            cross_session_memory_used=prepared.cross_session_turn_count,
                            nvidia_client=container.nvidia_client,
                            user_id=user_id,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "Streamed chat answer for session %s could not be persisted.",
                            request.session_id,
                        )
                        session_warning = (
                            "Answered successfully, but this turn could not be saved to session history."
                        )
                    else:
                        if container.history_service.should_generate_title(request.session_id, user_id=user_id):
                            asyncio.create_task(
                                container.history_service.generate_title(
                                    request.session_id,
                                    request.message,
                                    container.nvidia_client,
                                    user_id=user_id,
                                )
                            )

                yield _format_sse(
                    {
                        "type": "done",
                        "answer": answer,
                        "citations": [citation.model_dump(by_alias=True) for citation in citations],
                        "answerTrace": [step.model_dump(by_alias=True) for step in answer_trace],
                        "collectionId": request.collection_id,
                        "collectionLabel": collection_label,
                        "toolCall": (
                            prepared.tool_call.model_dump(by_alias=True)
                            if prepared.tool_call is not None
                            else None
                        ),
                        "webSearchRequested": request.web_search_enabled,
                        "webSearchUsed": prepared.web_search_used,
                        "offlineWarning": prepared.offline_warning,
                        "crossSessionMemoryUsed": prepared.cross_session_turn_count,
                        "modelThinking": model_thinking,
                        "thinkingRequested": recorded_thinking_requested,
                        "sessionWarning": session_warning,
                        "sessionTitle": None,
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                logger.exception("Chat stream failed for collection %s", request.collection_id)
                yield _format_sse({"type": "error", "message": "Chat stream failed."})
            finally:
                pending_tasks = [
                    task
                    for task in (history_task, prepared_task, generation_task)
                    if task is not None and not task.done()
                ]
                for task in pending_tasks:
                    task.cancel()
                if pending_tasks:
                    await asyncio.gather(*pending_tasks, return_exceptions=True)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _wait_with_keepalive(task: asyncio.Task[object], *, stage: str) -> AsyncIterator[str]:
    while True:
        done, _pending = await asyncio.wait({task}, timeout=KEEPALIVE_INTERVAL_SECONDS)
        if task in done:
            return
        yield _format_sse({"type": "heartbeat", "stage": stage})


async def _stream_finalized_answer(
    *,
    container: ServiceContainer,
    prepared: PreparedAnswer,
    thinking_enabled: bool,
    http_request: Request,
) -> FinalizedAnswer:
    attempt_order = [thinking_enabled]
    if thinking_enabled:
        attempt_order.append(False)

    for attempt_index, include_thinking in enumerate(attempt_order):
        raw_answer_parts: list[str] = []
        thinking_parts: list[str] = []
        emitted_response = False
        try:
            async for delta in container.nvidia_client.stream_answer(
                prompt=prepared.prompt,
                system_prompt=prepared.system_prompt,
                options=container.rag_service.generation_options_for(prepared),
                images=prepared.images,
                include_thinking=include_thinking,
                timeout=container.rag_service.generation_timeout_for(include_thinking=include_thinking),
            ):
                if await http_request.is_disconnected():
                    raise asyncio.CancelledError
                if delta.kind == "thinking":
                    thinking_parts.append(delta.content)
                    continue
                emitted_response = True
                raw_answer_parts.append(delta.content)

            finalized = container.rag_service.finalize_streamed_answer(
                "".join(raw_answer_parts),
                prepared.contexts,
                model_thinking=None,
            )
            if include_thinking:
                return finalized.__class__(
                    answer=finalized.answer,
                    citations=finalized.citations,
                    model_thinking=await container.rag_service.summarize_model_thinking(
                        [
                            *prepared.reasoning_segments,
                            *(
                                [f"Answer generation: {''.join(thinking_parts).strip()}"]
                                if "".join(thinking_parts).strip()
                                else []
                            ),
                        ],
                        question=prepared.question,
                        answer=finalized.answer,
                        contexts=prepared.contexts,
                    ),
                    generation_warning=finalized.generation_warning,
                )
            return finalized
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            if include_thinking and not emitted_response and attempt_index < len(attempt_order) - 1:
                logger.warning(
                    "Reasoning-enabled answer stream failed before any output; retrying without thinking mode.",
                    exc_info=True,
                )
                continue
            if prepared.contexts:
                logger.warning(
                    "Answer stream provider failed; falling back to retrieved evidence.",
                    exc_info=True,
                )
                return container.rag_service.fallback_from_contexts(
                    prepared.contexts,
                    reason="stream_interrupted",
                )
            raise

    raise RuntimeError("Streamed answer generation ended without a result.")
