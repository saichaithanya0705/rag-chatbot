export type SessionGroupLabel = "Today" | "Yesterday" | "Last 7 days" | "Older";

export interface SessionSummary {
  id: string;
  title: string;
  group: SessionGroupLabel;
}

export type MessageRole = "user" | "assistant";
export type MessageStatus = "complete" | "thinking";
export type PipelineStatus =
  | "queued"
  | "parsing"
  | "ocr"
  | "chunking"
  | "embedding"
  | "clustering"
  | "indexed"
  | "error";

export interface Citation {
  id: string;
  kind: "pdf" | "web";
  pdfName?: string;
  page?: number;
  chunkIndex?: number;
  excerpt?: string;
  url?: string;
  title?: string;
}

export interface PdfPreviewRequest {
  pdfName: string;
  page: number;
  chunkIndex: number;
  excerpt?: string;
}

export interface ToolCallBlock {
  label: string;
  query: string;
}

export interface AnswerTraceStep {
  kind: string;
  label: string;
  detail: string;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  citations: Citation[];
  answerTrace?: AnswerTraceStep[];
  modelThinking?: string;
  thinkingRequested?: boolean;
  collectionId?: string;
  collectionLabel?: string;
  crossSessionMemoryUsed?: number;
  toolCall?: ToolCallBlock;
  webSearchRequested?: boolean;
  webSearchUsed?: boolean;
  offlineWarning?: string;
  sessionWarning?: string;
}

export interface CollectionSummary {
  id: string;
  label: string;
}

export interface KnowledgeGraphNode {
  id: string;
  label: string;
  chunkCount: number;
  documentCount: number;
}

export interface KnowledgeGraphEdge {
  source: string;
  target: string;
  weight: number;
  directed?: boolean;
}

export interface KnowledgeGraph {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
}

export interface PipelineDocument {
  id: string;
  name: string;
  sizeLabel: string;
  pageCount: number;
  addedLabel: string;
  metaLabel?: string;
  status: PipelineStatus;
  progress: number;
  topics: string[];
  topicCollectionIds: string[];
  chunkCount: number;
  sharedTopicSummary?: string;
}

export interface PdfPreview {
  id: string;
  pdfName: string;
  page: number;
  totalPages: number;
  chunkIndex: number;
  htmlContent: string;
  fileUrl?: string;
}

export interface KnowledgeBaseSummary {
  indexedDocuments: number;
  indexedChunks: number;
  uploadHint: string;
}

export interface BootstrapPayload {
  sessions: SessionSummary[];
  activeSessionId: string;
  collections: CollectionSummary[];
  activeCollectionId: string;
  messagesBySession: Record<string, Message[]>;
  pipelineDocuments: PipelineDocument[];
  knowledgeGraph: KnowledgeGraph;
  knowledgeBaseSummary: KnowledgeBaseSummary;
}

export interface SendMessageInput {
  sessionId: string;
  text: string;
  collectionId: string;
  webSearchEnabled: boolean;
  thinkingEnabled: boolean;
}

export interface StreamMessageResult {
  message: Message;
  offlineWarning: string | null;
  sessionTitle?: string;
}

export interface IngestionProgressEvent {
  documentId: string;
  status: PipelineStatus;
  progress: number;
  error?: string;
}
