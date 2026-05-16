import {
  createContext,
  startTransition,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { httpWorkbenchGateway, type KnowledgeBaseRecord } from "@/shared/api/httpWorkbench";
import type {
  IngestionProgressEvent,
  Message,
  PipelineDocument,
  PipelineStatus,
} from "@/shared/api/types";
import {
  COMPACT_VIEWPORT_MEDIA_QUERY,
  createInitialWorkbenchState,
  persistThinkingEnabled,
} from "./workbenchInitialState";
import { useStableWorkbenchActions } from "./workbenchActions";
import { createWorkbenchPipelineActions } from "./workbenchPipelineActions";
import { createWorkbenchPreviewActions } from "./workbenchPreviewActions";
import { createWorkbenchSessionActions } from "./workbenchSessionActions";
import {
  appendMessages,
  buildPendingAnswerTrace,
  normalizeCollectionId,
  replaceMessage,
  resolveCollectionLabel,
  toStatusMap,
  updateMessage,
  updateMessageContent,
} from "./workbenchStateHelpers";
import type { WorkbenchContextValue, WorkbenchState } from "./workbenchTypes";

const WorkbenchContext = createContext<WorkbenchContextValue | null>(null);

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WorkbenchState>(createInitialWorkbenchState);
  const [ingestionStreamKey, setIngestionStreamKey] = useState(0);
  const toastTimeoutRef = useRef<number | null>(null);
  const titleSyncTimeoutRef = useRef<Map<string, number>>(new Map());
  const sendInFlightRef = useRef(false);
  const documentStatusRef = useRef<Record<string, PipelineStatus>>({});
  const pipelineDocumentsRef = useRef<PipelineDocument[]>(state.pipelineDocuments);
  const thinkingEnabledRef = useRef(state.thinkingEnabled);

  function showToast(message: string) {
    if (toastTimeoutRef.current !== null) {
      window.clearTimeout(toastTimeoutRef.current);
    }

    setState((previous) => ({
      ...previous,
      toastMessage: message,
    }));

    toastTimeoutRef.current = window.setTimeout(() => {
      setState((previous) => ({
        ...previous,
        toastMessage: null,
      }));
    }, 2800);
  }

  function mergeKnowledgeBase(knowledgeBase: KnowledgeBaseRecord) {
    setState((previous) => ({
      ...previous,
      collections: knowledgeBase.collections,
      activeCollectionId: normalizeCollectionId(knowledgeBase.collections, previous.activeCollectionId),
      pipelineDocuments: knowledgeBase.pipelineDocuments,
      knowledgeGraph: knowledgeBase.knowledgeGraph,
      knowledgeBaseSummary: knowledgeBase.knowledgeBaseSummary,
    }));
  }

  async function refreshKnowledgeBase(options?: { announceTransitions?: boolean }) {
    const knowledgeBase = await httpWorkbenchGateway.loadKnowledgeBase();
    const previousStatuses = documentStatusRef.current;
    const nextStatuses = toStatusMap(knowledgeBase.pipelineDocuments);
    documentStatusRef.current = nextStatuses;
    mergeKnowledgeBase(knowledgeBase);

    if (options?.announceTransitions !== false) {
      const completedDocument = knowledgeBase.pipelineDocuments.find((document) => {
        const previousStatus = previousStatuses[document.id];
        return (
          previousStatus !== undefined &&
          previousStatus !== document.status &&
          (document.status === "indexed" || document.status === "error")
        );
      });

      if (completedDocument) {
        showToast(
          completedDocument.status === "indexed"
            ? `${completedDocument.name} finished indexing.`
            : completedDocument.metaLabel ?? `${completedDocument.name} failed to index.`,
        );
      }
    }

    return knowledgeBase;
  }

  function applyIngestionProgress(event: IngestionProgressEvent) {
    setState((previous) => {
      const nextPipelineDocuments = previous.pipelineDocuments.map((document) =>
        document.id === event.documentId
          ? {
              ...document,
              status: event.status,
              progress: event.progress,
              metaLabel:
                event.status === "error"
                  ? event.error ?? document.metaLabel ?? "Indexing failed."
                  : document.metaLabel,
            }
          : document,
      );
      documentStatusRef.current = toStatusMap(nextPipelineDocuments);
      return {
        ...previous,
        pipelineDocuments: nextPipelineDocuments,
      };
    });
  }

  async function loadBootstrap() {
    const payload = await httpWorkbenchGateway.bootstrap();
    documentStatusRef.current = toStatusMap(payload.pipelineDocuments);
    setState((previous) => ({
      ...previous,
      isBootstrapping: false,
      isReclustering: false,
      isSendingMessage: false,
      sessions: payload.sessions,
      activeSessionId: payload.activeSessionId,
      collections: payload.collections,
      activeCollectionId: payload.activeCollectionId,
      messagesBySession: payload.messagesBySession,
      pipelineDocuments: payload.pipelineDocuments,
      knowledgeGraph: payload.knowledgeGraph,
      knowledgeBaseSummary: payload.knowledgeBaseSummary,
      bootstrapError: null,
      sidebarOpen: previous.isCompactViewport ? false : true,
      webSearchEnabled: true,
      webSearchOffline: false,
      thinkingEnabled: previous.thinkingEnabled,
      pdfPreview: null,
      pdfPreviewError: null,
      pdfPreviewRequest: null,
      isPdfPreviewLoading: false,
      toastMessage: null,
    }));
  }

  useEffect(() => {
    let alive = true;

    void (async () => {
      try {
        await loadBootstrap();
        if (!alive) {
          return;
        }
      } catch (error) {
        if (!alive) {
          return;
        }

        setState((previous) => ({
          ...previous,
          isBootstrapping: false,
          isReclustering: false,
          isSendingMessage: false,
          bootstrapError: httpWorkbenchGateway.resolveErrorMessage(error),
          toastMessage: null,
        }));
      }
    })();

    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const mediaQuery = window.matchMedia(COMPACT_VIEWPORT_MEDIA_QUERY);
    const handleViewportChange = (event: MediaQueryListEvent | MediaQueryList) => {
      setState((previous) => {
        const isCompactViewport = event.matches;
        if (previous.isCompactViewport === isCompactViewport) {
          return previous;
        }

        return {
          ...previous,
          isCompactViewport,
          sidebarOpen: isCompactViewport ? false : true,
        };
      });
    };

    handleViewportChange(mediaQuery);

    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", handleViewportChange);
      return () => {
        mediaQuery.removeEventListener("change", handleViewportChange);
      };
    }

    mediaQuery.addListener(handleViewportChange);
    return () => {
      mediaQuery.removeListener(handleViewportChange);
    };
  }, []);

  useEffect(() => {
    pipelineDocumentsRef.current = state.pipelineDocuments;
  }, [state.pipelineDocuments]);

  useEffect(() => {
    thinkingEnabledRef.current = state.thinkingEnabled;
  }, [state.thinkingEnabled]);

  const activeIngestionSignature = state.pipelineDocuments
    .filter((document) => document.status !== "indexed" && document.status !== "error")
    .map((document) => document.id)
    .sort()
    .join("|");

  useEffect(() => {
    return () => {
      if (toastTimeoutRef.current !== null) {
        window.clearTimeout(toastTimeoutRef.current);
      }

      titleSyncTimeoutRef.current.forEach((timeoutId) => {
        window.clearTimeout(timeoutId);
      });
      titleSyncTimeoutRef.current.clear();
    };
  }, []);

  useEffect(() => {
    if (!activeIngestionSignature) {
      return;
    }

    let disposed = false;
    const unsubscribe = httpWorkbenchGateway.subscribeIngestionProgress(
      (event) => {
        if (disposed) {
          return;
        }

        applyIngestionProgress(event);
        if (event.status === "indexed" || event.status === "error") {
          void refreshKnowledgeBase().catch(() => undefined);
        }
      },
      () => {
        if (disposed) {
          return;
        }

        void refreshKnowledgeBase({ announceTransitions: false })
          .catch(() => undefined)
          .finally(() => {
            if (
              !disposed &&
              pipelineDocumentsRef.current.some(
                (document) => document.status !== "indexed" && document.status !== "error",
              )
            ) {
              setIngestionStreamKey((previous) => previous + 1);
            }
          });
      },
    );

    return () => {
      disposed = true;
      unsubscribe();
    };
  }, [activeIngestionSignature, ingestionStreamKey]);

  const { refreshSessions, scheduleSessionTitleRefresh, createSession, selectSession, deleteSession } =
    createWorkbenchSessionActions({
      state,
      setState,
      titleSyncTimeoutRef,
      showToast,
    });
  const { openPdfPreview, goToPdfPreviewPage, retryPdfPreview, closePdfPreview } = createWorkbenchPreviewActions({
    state,
    setState,
    showToast,
  });
  const { uploadDocuments, reclusterTopics, removePipelineDocument } = createWorkbenchPipelineActions({
    state,
    setState,
    showToast,
    mergeKnowledgeBase,
    refreshKnowledgeBase,
    documentStatusRef,
  });

  async function retryBootstrap() {
    setState((previous) => ({
      ...previous,
      isBootstrapping: true,
      bootstrapError: null,
      pdfPreview: null,
      pdfPreviewError: null,
      pdfPreviewRequest: null,
      isPdfPreviewLoading: false,
    }));

    try {
      await loadBootstrap();
    } catch (error) {
      setState((previous) => ({
        ...previous,
        isBootstrapping: false,
        bootstrapError: httpWorkbenchGateway.resolveErrorMessage(error),
      }));
    }
  }

  function toggleSidebar() {
    setState((previous) => ({
      ...previous,
      sidebarOpen: !previous.sidebarOpen,
    }));
  }

  function setSidebarOpen(nextValue: boolean) {
    setState((previous) => ({
      ...previous,
      sidebarOpen: nextValue,
    }));
  }

  function selectCollection(collectionId: string) {
    setState((previous) =>
      previous.isSendingMessage
        ? previous
        : {
            ...previous,
            activeCollectionId: normalizeCollectionId(previous.collections, collectionId),
          },
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
      previous.isSendingMessage
        ? previous
        : {
            ...previous,
            webSearchEnabled: !previous.webSearchEnabled,
            webSearchOffline: previous.webSearchEnabled ? false : previous.webSearchOffline,
          },
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

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || !state.activeSessionId || sendInFlightRef.current) {
      return;
    }

    sendInFlightRef.current = true;
    const activeSessionId = state.activeSessionId;
    const requestedCollectionId = normalizeCollectionId(state.collections, state.activeCollectionId);
    const requestedCollectionLabel = resolveCollectionLabel(state.collections, requestedCollectionId);
    const webSearchRequested = state.webSearchEnabled;
    const thinkingEnabled = Boolean(thinkingEnabledRef.current);
    const pendingAnswerTrace = buildPendingAnswerTrace(requestedCollectionLabel, webSearchRequested);

    const assistantMessageId = `assistant-${crypto.randomUUID()}`;
    const userMessage: Message = {
      id: `user-${crypto.randomUUID()}`,
      role: "user",
      content: trimmed,
      status: "complete",
      citations: [],
      collectionId: requestedCollectionId,
      collectionLabel: requestedCollectionLabel,
      webSearchRequested,
    };

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
      sendInFlightRef.current = false;
      setState((previous) => ({
        ...previous,
        isSendingMessage: false,
      }));
    }
  }

  function clearToast() {
    setState((previous) => ({
      ...previous,
      toastMessage: null,
    }));
  }

  const stableActions = useStableWorkbenchActions({
    retryBootstrap,
    createSession,
    selectSession,
    deleteSession,
    toggleSidebar,
    setSidebarOpen,
    selectCollection,
    setDraftMessage,
    toggleWebSearch,
    toggleThinking,
    sendMessage,
    openPdfPreview,
    goToPdfPreviewPage,
    retryPdfPreview,
    closePdfPreview,
    uploadDocuments,
    reclusterTopics,
    removePipelineDocument,
    clearToast,
  });

  const value: WorkbenchContextValue = useMemo(
    () => ({ state, actions: stableActions }),
    [state, stableActions],
  );

  return <WorkbenchContext.Provider value={value}>{children}</WorkbenchContext.Provider>;
}

export function useWorkbench() {
  const context = useContext(WorkbenchContext);
  if (!context) {
    throw new Error("useWorkbench must be used inside WorkbenchProvider");
  }

  return context;
}
