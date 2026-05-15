import type {
  Citation,
  CollectionSummary,
  KnowledgeBaseSummary,
  KnowledgeGraph,
  Message,
  PdfPreview,
  PdfPreviewRequest,
  PipelineDocument,
  SessionSummary,
} from "@/shared/api/types";

export interface WorkbenchState {
  isBootstrapping: boolean;
  isReclustering: boolean;
  isSendingMessage: boolean;
  isCompactViewport: boolean;
  isPdfPreviewLoading: boolean;
  pendingSessionAction: "create" | "select" | "delete" | null;
  pendingSessionTargetId: string | null;
  sessions: SessionSummary[];
  activeSessionId: string;
  collections: CollectionSummary[];
  activeCollectionId: string;
  messagesBySession: Record<string, Message[]>;
  pipelineDocuments: PipelineDocument[];
  knowledgeGraph: KnowledgeGraph;
  knowledgeBaseSummary: KnowledgeBaseSummary;
  bootstrapError: string | null;
  draftMessage: string;
  sidebarOpen: boolean;
  webSearchEnabled: boolean;
  webSearchOffline: boolean;
  thinkingEnabled: boolean;
  pdfPreview: PdfPreview | null;
  pdfPreviewError: string | null;
  pdfPreviewRequest: PdfPreviewRequest | null;
  toastMessage: string | null;
}

export interface WorkbenchActions {
  retryBootstrap: () => Promise<void>;
  createSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  toggleSidebar: () => void;
  setSidebarOpen: (nextValue: boolean) => void;
  selectCollection: (collectionId: string) => void;
  setDraftMessage: (nextValue: string) => void;
  toggleWebSearch: () => void;
  toggleThinking: () => void;
  sendMessage: (text: string) => Promise<void>;
  openPdfPreview: (citation: Citation) => Promise<void>;
  goToPdfPreviewPage: (page: number) => Promise<void>;
  retryPdfPreview: () => Promise<void>;
  closePdfPreview: () => void;
  uploadDocuments: (files: File[]) => Promise<void>;
  reclusterTopics: () => Promise<void>;
  removePipelineDocument: (documentId: string) => Promise<void>;
  clearToast: () => void;
}

export interface WorkbenchContextValue {
  state: WorkbenchState;
  actions: WorkbenchActions;
}
