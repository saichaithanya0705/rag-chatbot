import type { WorkbenchState } from "./workbenchTypes";

export const COMPACT_VIEWPORT_MEDIA_QUERY = "(max-width: 960px)";
export const THINKING_ENABLED_STORAGE_KEY = "local-rag-chat/thinking-enabled";
export const DETAILED_ANSWER_STORAGE_KEY = "local-rag-chat/detailed-answer-enabled";

export function getInitialCompactViewport() {
  return typeof window !== "undefined" && window.matchMedia(COMPACT_VIEWPORT_MEDIA_QUERY).matches;
}

export function getInitialThinkingEnabled() {
  if (typeof window === "undefined") {
    return true;
  }

  const storedValue = window.localStorage.getItem(THINKING_ENABLED_STORAGE_KEY);
  if (storedValue === null) {
    return true;
  }

  return storedValue === "true";
}

export function persistThinkingEnabled(nextValue: boolean) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(THINKING_ENABLED_STORAGE_KEY, String(nextValue));
}

export function getInitialDetailedAnswerEnabled() {
  if (typeof window === "undefined") {
    return false;
  }

  const storedValue = window.localStorage.getItem(DETAILED_ANSWER_STORAGE_KEY);
  if (storedValue === null) {
    return false;
  }

  return storedValue === "true";
}

export function persistDetailedAnswerEnabled(nextValue: boolean) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(DETAILED_ANSWER_STORAGE_KEY, String(nextValue));
}

export function createInitialWorkbenchState(): WorkbenchState {
  const isCompactViewport = getInitialCompactViewport();

  return {
    isBootstrapping: true,
    isReclustering: false,
    isSendingMessage: false,
    isCompactViewport,
    isPdfPreviewLoading: false,
    pendingSessionAction: null,
    pendingSessionTargetId: null,
    sessions: [],
    activeSessionId: "",
    collections: [],
    activeCollectionId: "",
    messagesBySession: {},
    pipelineDocuments: [],
    knowledgeGraph: {
      nodes: [],
      edges: [],
    },
    knowledgeBaseSummary: {
      indexedDocuments: 0,
      indexedChunks: 0,
      uploadHint: "",
    },
    bootstrapError: null,
    draftMessage: "",
    sidebarOpen: !isCompactViewport,
    webSearchEnabled: true,
    webSearchOffline: false,
    thinkingEnabled: getInitialThinkingEnabled(),
    detailedAnswerEnabled: getInitialDetailedAnswerEnabled(),
    pdfPreview: null,
    pdfPreviewError: null,
    pdfPreviewRequest: null,
    toastMessage: null,
    draftImages: [],
    thinkingSupported: false,
  };
}
