import { startTransition, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { httpWorkbenchGateway } from "@/shared/api/httpWorkbench";
import type { Message } from "@/shared/api/types";
import { persistThinkingEnabled, persistDetailedAnswerEnabled } from "./workbenchInitialState";
import {
  appendMessages,
  buildPendingAnswerTrace,
  hasDraftSubmissionContent,
  normalizeCollectionId,
  removeMessages,
  replaceMessage,
  resolveCollectionLabel,
  updateMessage,
  updateMessageContent,
} from "./workbenchStateHelpers";
import type { WorkbenchState } from "./workbenchTypes";

interface ChatActionDeps {
  state: WorkbenchState;
  setState: Dispatch<SetStateAction<WorkbenchState>>;
  sendInFlightRef: MutableRefObject<boolean>;
  activeChatAbortControllerRef: MutableRefObject<AbortController | null>;
  thinkingEnabledRef: MutableRefObject<boolean>;
  detailedAnswerEnabledRef: MutableRefObject<boolean>;
  titleSyncTimeoutRef: MutableRefObject<Map<string, number>>;
  showToast: (message: string) => void;
  refreshSessions: (preferredSessionId?: string) => Promise<void>;
  scheduleSessionTitleRefresh: (sessionId: string) => void;
}

function canChangeCollection(previous: WorkbenchState) {
  return !previous.isSendingMessage;
}

export function createWorkbenchChatActions({
  state,
  setState,
  sendInFlightRef,
  activeChatAbortControllerRef,
  thinkingEnabledRef,
  detailedAnswerEnabledRef,
  titleSyncTimeoutRef,
  showToast,
  refreshSessions,
  scheduleSessionTitleRefresh,
}: ChatActionDeps) {
  function selectCollection(collectionId: string) {
    setState((previous) =>
      canChangeCollection(previous)
        ? {
            ...previous,
            activeCollectionId: normalizeCollectionId(previous.collections, collectionId),
          }
        : previous,
    );
  }

  function setDraftMessage(nextValue: string) {
    setState((previous) => ({
      ...previous,
      draftMessage: nextValue,
    }));
  }

  function toggleWebSearch() {
    setState((previous) =>
      canChangeCollection(previous)
        ? {
            ...previous,
            webSearchEnabled: !previous.webSearchEnabled,
            webSearchOffline: previous.webSearchEnabled ? false : previous.webSearchOffline,
          }
        : previous,
    );
  }

  function toggleThinking() {
    setState((previous) => {
      if (previous.isSendingMessage) {
        return previous;
      }

      const nextValue = !previous.thinkingEnabled;
      persistThinkingEnabled(nextValue);
      return {
        ...previous,
        thinkingEnabled: nextValue,
      };
    });
  }

  function toggleDetailedAnswer() {
    setState((previous) => {
      if (previous.isSendingMessage) {
        return previous;
      }

      const nextValue = !previous.detailedAnswerEnabled;
      persistDetailedAnswerEnabled(nextValue);
      return {
        ...previous,
        detailedAnswerEnabled: nextValue,
      };
    });
  }

  function stopMessage() {
    activeChatAbortControllerRef.current?.abort();
  }

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    const currentImages = state.draftImages;
    if (!hasDraftSubmissionContent(text, currentImages.length) || !state.activeSessionId || sendInFlightRef.current) {
      return;
    }

    const abortController = new AbortController();
    sendInFlightRef.current = true;
    activeChatAbortControllerRef.current = abortController;
    const activeSessionId = state.activeSessionId;
    const requestedCollectionId = normalizeCollectionId(state.collections, state.activeCollectionId);
    const requestedCollectionLabel = resolveCollectionLabel(state.collections, requestedCollectionId);
    const webSearchRequested = state.webSearchEnabled;
    const thinkingEnabled = Boolean(thinkingEnabledRef.current);
    const previousDraftMessage = text;
    const previousDraftImages = state.draftImages;
    const previousWebSearchOffline = state.webSearchOffline;
    const pendingAnswerTrace = buildPendingAnswerTrace(requestedCollectionLabel, webSearchRequested);

    const assistantMessageId = `assistant-${crypto.randomUUID()}`;
    const userMessageId = `user-${crypto.randomUUID()}`;
    const userMessage: Message = {
      id: userMessageId,
      role: "user",
      content: trimmed,
      status: "complete",
      citations: [],
      collectionId: requestedCollectionId,
      collectionLabel: requestedCollectionLabel,
      webSearchRequested,
      images: currentImages,
    };

    const responseLength = detailedAnswerEnabledRef.current ? "comprehensive" : "standard";

    const thinkingMessage: Message = {
      id: assistantMessageId,
      role: "assistant",
      content: "Thinking...",
      status: "thinking",
      citations: [],
      answerTrace: pendingAnswerTrace,
      collectionId: requestedCollectionId,
      collectionLabel: requestedCollectionLabel,
      webSearchRequested,
      thinkingRequested: thinkingEnabled,
      modelThinking: undefined,
    };

    setState((previous) => ({
      ...previous,
      isSendingMessage: true,
      draftMessage: "",
      draftImages: [],
      webSearchOffline: false,
      messagesBySession: appendMessages(previous.messagesBySession, previous.activeSessionId, [
        userMessage,
        thinkingMessage,
      ]),
      pdfPreview: null,
      pdfPreviewError: null,
      pdfPreviewRequest: null,
      isPdfPreviewLoading: false,
    }));

    let streamedContent = "";
    const shouldWaitForGeneratedTitle = state.sessions.some(
      (session) => session.id === activeSessionId && session.title === "New chat",
    );

    try {
      const assistantResult = await httpWorkbenchGateway.streamMessage(
        {
          sessionId: activeSessionId,
          text: trimmed,
          collectionId: requestedCollectionId,
          webSearchEnabled: webSearchRequested,
          thinkingEnabled,
          responseLength,
          images: currentImages.map(({ data, mimeType }) => ({ data, mimeType })),
        },
        {
          onToken: (delta) => {
            streamedContent += delta;
            setState((previous) => ({
              ...previous,
              messagesBySession: updateMessageContent(
                previous.messagesBySession,
                activeSessionId,
                assistantMessageId,
                streamedContent || "Thinking...",
              ),
            }));
          },
          onTool: (toolCall, offlineWarning) => {
            setState((previous) => ({
              ...previous,
              webSearchOffline: Boolean(offlineWarning),
              messagesBySession: updateMessage(
                previous.messagesBySession,
                activeSessionId,
                assistantMessageId,
                (message) => ({
                  ...message,
                  toolCall,
                  offlineWarning: offlineWarning ?? message.offlineWarning,
                }),
              ),
            }));

            if (offlineWarning) {
              showToast(offlineWarning);
            }
          },
        },
        { signal: abortController.signal },
      );

      startTransition(() => {
        setState((previous) => ({
          ...previous,
          webSearchOffline: Boolean(assistantResult.offlineWarning),
          sessions: assistantResult.sessionTitle
            ? previous.sessions.map((session) =>
                session.id === activeSessionId
                  ? { ...session, title: assistantResult.sessionTitle ?? session.title }
                  : session,
              )
            : previous.sessions,
          messagesBySession: replaceMessage(
            previous.messagesBySession,
            activeSessionId,
            assistantMessageId,
            {
              ...assistantResult.message,
              id: assistantMessageId,
              collectionId: assistantResult.message.collectionId ?? requestedCollectionId,
              collectionLabel: assistantResult.message.collectionLabel ?? requestedCollectionLabel,
              webSearchRequested: assistantResult.message.webSearchRequested ?? webSearchRequested,
              thinkingRequested: assistantResult.message.thinkingRequested ?? thinkingEnabled,
            },
          ),
        }));
      });

      if (assistantResult.sessionTitle) {
        const existingTimeout = titleSyncTimeoutRef.current.get(activeSessionId);
        if (existingTimeout !== undefined) {
          window.clearTimeout(existingTimeout);
          titleSyncTimeoutRef.current.delete(activeSessionId);
        }
      }

      if (assistantResult.message.sessionWarning) {
        showToast(assistantResult.message.sessionWarning);
      }

      void refreshSessions(activeSessionId);
      if (!assistantResult.sessionTitle && shouldWaitForGeneratedTitle) {
        scheduleSessionTitleRefresh(activeSessionId);
      }
    } catch (error) {
      if (httpWorkbenchGateway.isAbortError(error)) {
        setState((previous) => ({
          ...previous,
          draftMessage: previousDraftMessage,
          draftImages: previousDraftImages,
          webSearchOffline: previousWebSearchOffline,
          messagesBySession: removeMessages(previous.messagesBySession, activeSessionId, [
            userMessageId,
            assistantMessageId,
          ]),
        }));
        showToast("Response stopped. Your draft was restored.");
        return;
      }

      const errorMessage = httpWorkbenchGateway.resolveErrorMessage(error);
      setState((previous) => ({
        ...previous,
        messagesBySession: replaceMessage(
          previous.messagesBySession,
          activeSessionId,
          assistantMessageId,
          {
            id: assistantMessageId,
            role: "assistant",
            content: errorMessage,
            status: "complete",
            citations: [],
            answerTrace: pendingAnswerTrace,
            collectionId: requestedCollectionId,
            collectionLabel: requestedCollectionLabel,
            webSearchRequested,
            thinkingRequested: thinkingEnabled,
            modelThinking: undefined,
          },
        ),
      }));
    } finally {
      if (activeChatAbortControllerRef.current === abortController) {
        activeChatAbortControllerRef.current = null;
      }
      sendInFlightRef.current = false;
      setState((previous) => ({
        ...previous,
        isSendingMessage: false,
      }));
    }
  }

  return {
    selectCollection,
    setDraftMessage,
    toggleWebSearch,
    toggleThinking,
    toggleDetailedAnswer,
    sendMessage,
    stopMessage,
  };
}
