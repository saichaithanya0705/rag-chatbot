import {
  createContext,
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
  PipelineDocument,
  PipelineStatus,
} from "@/shared/api/types";
import {
  COMPACT_VIEWPORT_MEDIA_QUERY,
  createInitialWorkbenchState,
  persistTheme,
} from "./workbenchInitialState";
import { useStableWorkbenchActions } from "./workbenchActions";
import { createWorkbenchChatActions } from "./workbenchChatActions";
import { createWorkbenchPipelineActions } from "./workbenchPipelineActions";
import { createWorkbenchPreviewActions } from "./workbenchPreviewActions";
import { createWorkbenchSessionActions } from "./workbenchSessionActions";
import {
  normalizeCollectionId,
  toStatusMap,
} from "./workbenchStateHelpers";
import type { WorkbenchContextValue, WorkbenchState } from "./workbenchTypes";

const WorkbenchContext = createContext<WorkbenchContextValue | null>(null);

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WorkbenchState>(createInitialWorkbenchState);
  const [ingestionStreamKey, setIngestionStreamKey] = useState(0);
  const toastTimeoutRef = useRef<number | null>(null);
  const titleSyncTimeoutRef = useRef<Map<string, number>>(new Map());
  const sendInFlightRef = useRef(false);
  const activeChatAbortControllerRef = useRef<AbortController | null>(null);
  const documentStatusRef = useRef<Record<string, PipelineStatus>>({});
  const pipelineDocumentsRef = useRef<PipelineDocument[]>(state.pipelineDocuments);
  const thinkingEnabledRef = useRef(state.thinkingEnabled);
  const detailedAnswerEnabledRef = useRef(state.detailedAnswerEnabled);

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
      thinkingSupported: payload.thinkingSupported,
      bootstrapError: null,
      sidebarOpen: previous.isCompactViewport ? false : true,
      webSearchEnabled: true,
      webSearchOffline: false,
      thinkingEnabled: payload.thinkingSupported ? previous.thinkingEnabled : false,
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
    document.documentElement.setAttribute("data-theme", state.theme);
  }, [state.theme]);

  useEffect(() => {
    pipelineDocumentsRef.current = state.pipelineDocuments;
  }, [state.pipelineDocuments]);

  useEffect(() => {
    thinkingEnabledRef.current = state.thinkingEnabled;
  }, [state.thinkingEnabled]);

  useEffect(() => {
    detailedAnswerEnabledRef.current = state.detailedAnswerEnabled;
  }, [state.detailedAnswerEnabled]);

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

      activeChatAbortControllerRef.current?.abort();
      activeChatAbortControllerRef.current = null;
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
  const { selectCollection, setDraftMessage, toggleWebSearch, toggleThinking, toggleDetailedAnswer, sendMessage, stopMessage } =
    createWorkbenchChatActions({
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

  function toggleTheme() {
    setState((previous) => {
      const nextTheme = previous.theme === "light" ? "dark" : "light";
      persistTheme(nextTheme);
      return {
        ...previous,
        theme: nextTheme,
      };
    });
  }

  function clearToast() {
    setState((previous) => ({
      ...previous,
      toastMessage: null,
    }));
  }

  function addDraftImage(image: { data: string; mimeType: string; url: string }) {
    setState((previous) => ({
      ...previous,
      draftImages: [...previous.draftImages, image],
    }));
  }

  function removeDraftImage(index: number) {
    setState((previous) => ({
      ...previous,
      draftImages: previous.draftImages.filter((_, idx) => idx !== index),
    }));
  }

  function clearDraftImages() {
    setState((previous) => ({
      ...previous,
      draftImages: [],
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
    toggleDetailedAnswer,
    sendMessage,
    stopMessage,
    openPdfPreview,
    goToPdfPreviewPage,
    retryPdfPreview,
    closePdfPreview,
    uploadDocuments,
    reclusterTopics,
    removePipelineDocument,
    clearToast,
    addDraftImage,
    removeDraftImage,
    clearDraftImages,
    toggleTheme,
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
