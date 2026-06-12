import type {
  BootstrapPayload,
  Citation,
  CollectionSummary,
  IngestionProgressEvent,
  KnowledgeBaseSummary,
  KnowledgeGraph,
  Message,
  PdfPreview,
  PdfPreviewRequest,
  PipelineDocument,
  SendMessageInput,
  SessionSummary,
  StreamMessageResult,
} from "@/shared/api/types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const ROOT_COLLECTION: CollectionSummary = { id: "all-pdfs", label: "All PDFs" };
const USER_ID_STORAGE_KEY = "local-rag-chat/user-id";

interface IndexedDocumentApiResponse {
  id: string;
  pdf_name: string;
  sizeLabel: string;
  page_count: number;
  chunk_count: number;
  status: PipelineDocument["status"];
  progress: number;
  errorMessage?: string | null;
  created_at: string;
  updatedAt: string;
  topics: string[];
  topicCollectionIds?: string[];
  sharedTopicSummary?: string | null;
}

interface TopicSummaryApiResponse {
  id: string;
  label: string;
  chunkCount: number;
  documentCount: number;
}

interface GraphNodeApiResponse {
  id: string;
  label: string;
  chunkCount: number;
  documentCount: number;
  keywords?: string[];
  sourceDocuments?: string[];
  pageKeys?: string[];
}

interface GraphEdgeApiResponse {
  source: string;
  target: string;
  weight: number;
  directed?: boolean;
  semanticScore?: number;
  pageOverlapScore?: number;
  documentOverlapScore?: number;
  sharedPages?: string[];
  sharedDocuments?: string[];
  reason?: string;
}

interface GraphApiResponse {
  nodes: GraphNodeApiResponse[];
  edges: GraphEdgeApiResponse[];
}

interface ReclusterApiResponse {
  topics: TopicSummaryApiResponse[];
  indexedChunks: number;
  documentCount: number;
}

interface SessionSummaryApiResponse {
  id: string;
  title: string;
  group: SessionSummary["group"];
  collectionId: string;
  updatedAt: string;
}

interface SessionMessageApiResponse {
  id: string;
  role: Message["role"];
  content: string;
  citations: CitationApiResponse[];
  answerTrace?: AnswerTraceApiResponse[];
  modelThinking?: string | null;
  thinkingRequested?: boolean;
  collectionId?: string;
  collectionLabel?: string;
  crossSessionMemoryUsed?: number;
  toolCall?: ToolCallApiResponse | null;
  webSearchRequested?: boolean;
  webSearchUsed?: boolean;
  offlineWarning?: string | null;
  createdAt: string;
}

interface SessionDetailApiResponse extends SessionSummaryApiResponse {
  messages: SessionMessageApiResponse[];
}

interface CreateSessionApiRequest {
  collectionId: string;
}

interface PreviewApiResponse {
  pdfName: string;
  page: number;
  totalPages: number;
  htmlContent: string;
  fileUrl?: string;
}

interface StreamTokenPayload {
  type: "token";
  delta: string;
}

interface StreamDonePayload {
  type: "done";
  answer: string;
  citations: CitationApiResponse[];
  answerTrace?: AnswerTraceApiResponse[];
  modelThinking?: string | null;
  thinkingRequested?: boolean;
  collectionId?: string;
  collectionLabel?: string;
  crossSessionMemoryUsed?: number;
  toolCall?: ToolCallApiResponse | null;
  webSearchRequested?: boolean;
  webSearchUsed?: boolean;
  offlineWarning?: string | null;
  sessionWarning?: string | null;
  sessionTitle?: string | null;
}

interface StreamToolPayload {
  type: "tool";
  toolCall: ToolCallApiResponse;
  offlineWarning?: string | null;
}

interface StreamStatusPayload {
  type: "status";
  stage: string;
  message: string;
}

interface StreamHeartbeatPayload {
  type: "heartbeat";
  stage: string;
}

interface StreamErrorPayload {
  type: "error";
  message: string;
}

type StreamPayload =
  | StreamTokenPayload
  | StreamDonePayload
  | StreamToolPayload
  | StreamStatusPayload
  | StreamHeartbeatPayload
  | StreamErrorPayload;

interface StreamHandlers {
  onToken: (delta: string) => void;
  onTool: (toolCall: ToolCallApiResponse, offlineWarning?: string | null) => void;
}

interface StreamRequestOptions {
  signal?: AbortSignal;
}

interface IngestionProgressApiResponse {
  documentId: string;
  status: PipelineDocument["status"];
  progress: number;
  error?: string;
}

function parseSsePayload<T>(rawEvent: string): T | null {
  const data = rawEvent
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");

  if (!data) {
    return null;
  }

  return JSON.parse(data) as T;
}

function readSseEvents(buffer: string): { events: string[]; remaining: string } {
  const events: string[] = [];
  let remaining = buffer;

  while (true) {
    const boundary = remaining.match(/\r?\n\r?\n/);
    if (!boundary || boundary.index === undefined) {
      return { events, remaining };
    }

    events.push(remaining.slice(0, boundary.index));
    remaining = remaining.slice(boundary.index + boundary[0].length);
  }
}

export interface SessionDetailRecord {
  session: SessionSummary;
  collectionId: string;
  messages: Message[];
}

export interface KnowledgeBaseRecord {
  collections: CollectionSummary[];
  pipelineDocuments: PipelineDocument[];
  knowledgeGraph: KnowledgeGraph;
  knowledgeBaseSummary: KnowledgeBaseSummary;
}

interface CitationApiResponse {
  id: string;
  kind: Citation["kind"];
  pdfName?: string | null;
  page?: number | null;
  chunkIndex?: number | null;
  excerpt?: string;
  parser?: string | null;
  sourceText?: string | null;
  sourceLabels?: string[] | null;
  sourceRefs?: string[] | null;
  sourceBlocks?: Array<Record<string, unknown>> | null;
  sourceLocation?: string | null;
  hasTable?: boolean | null;
  url?: string | null;
  title?: string | null;
}

interface ToolCallApiResponse {
  label: string;
  query: string;
}

interface AnswerTraceApiResponse {
  kind: string;
  label: string;
  detail: string;
}

function resolveErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }

  return "The backend request failed.";
}

function isAbortError(error: unknown) {
  if (typeof DOMException !== "undefined" && error instanceof DOMException) {
    return error.name === "AbortError";
  }

  return error instanceof Error && error.name === "AbortError";
}

function getClientUserId() {
  if (typeof window === "undefined") {
    return "default";
  }

  const existing = window.localStorage.getItem(USER_ID_STORAGE_KEY);
  if (existing) {
    return existing;
  }

  const nextValue = crypto.randomUUID();
  window.localStorage.setItem(USER_ID_STORAGE_KEY, nextValue);
  return nextValue;
}

function buildHeaders(headers?: HeadersInit) {
  const nextHeaders = new Headers(headers);
  nextHeaders.set("x-user-id", getClientUserId());
  return nextHeaders;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: buildHeaders(init?.headers),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Request failed with status ${response.status}.`);
  }

  return (await response.json()) as T;
}

async function requestNoContent(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: buildHeaders(init?.headers),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Request failed with status ${response.status}.`);
  }
}

function formatIndexedLabel(createdAt: string) {
  const createdAtDate = new Date(createdAt);
  if (Number.isNaN(createdAtDate.getTime())) {
    return "Updated recently";
  }

  const diffMs = Date.now() - createdAtDate.getTime();
  if (diffMs < 60_000) {
    return "Updated just now";
  }

  const diffHours = Math.floor(diffMs / 3_600_000);
  if (diffHours < 24) {
    return `Updated ${diffHours} hour${diffHours === 1 ? "" : "s"} ago`;
  }

  const diffDays = Math.floor(diffHours / 24);
  return `Updated ${diffDays} day${diffDays === 1 ? "" : "s"} ago`;
}

function mapCitation(citation: CitationApiResponse): Citation {
  return {
    id: citation.id,
    kind: citation.kind,
    pdfName: citation.pdfName ?? undefined,
    page: citation.page ?? undefined,
    chunkIndex: citation.chunkIndex ?? undefined,
    excerpt: citation.excerpt,
    parser: citation.parser ?? undefined,
    sourceText: citation.sourceText ?? undefined,
    sourceLabels: citation.sourceLabels ?? undefined,
    sourceRefs: citation.sourceRefs ?? undefined,
    sourceBlocks: citation.sourceBlocks ?? undefined,
    sourceLocation: citation.sourceLocation ?? undefined,
    hasTable: citation.hasTable ?? undefined,
    url: citation.url ?? undefined,
    title: citation.title ?? undefined,
  };
}

function mapIndexedDocument(document: IndexedDocumentApiResponse): PipelineDocument {
  const metaLabel =
    document.status === "error"
      ? document.errorMessage ?? "Indexing failed."
      : `${document.sizeLabel} · ${document.page_count || 0} pages${
          document.updatedAt ? ` · ${formatIndexedLabel(document.updatedAt)}` : ""
        }`;

  return {
    id: document.id,
    name: document.pdf_name,
    sizeLabel: document.sizeLabel,
    pageCount: document.page_count,
    addedLabel: formatIndexedLabel(document.updatedAt ?? document.created_at),
    metaLabel,
    status: document.status,
    progress: document.progress,
    topics: document.topics,
    topicCollectionIds: document.topicCollectionIds ?? [],
    chunkCount: document.chunk_count,
    sharedTopicSummary: document.sharedTopicSummary ?? undefined,
  };
}

function mapSessionSummary(session: SessionSummaryApiResponse): SessionSummary {
  return {
    id: session.id,
    title: session.title,
    group: session.group,
  };
}

function mapSessionMessage(message: SessionMessageApiResponse): Message {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    status: "complete",
    citations: message.citations.map(mapCitation),
    answerTrace: message.answerTrace ?? [],
    modelThinking: message.modelThinking ?? undefined,
    thinkingRequested: message.thinkingRequested ?? Boolean(message.modelThinking),
    collectionId: message.collectionId ?? ROOT_COLLECTION.id,
    collectionLabel: message.collectionLabel ?? message.collectionId ?? ROOT_COLLECTION.label,
    crossSessionMemoryUsed: message.crossSessionMemoryUsed ?? 0,
    toolCall: message.toolCall ?? undefined,
    webSearchRequested: message.webSearchRequested ?? true,
    webSearchUsed: message.webSearchUsed ?? false,
    offlineWarning: message.offlineWarning ?? undefined,
  };
}

function mapSessionDetail(detail: SessionDetailApiResponse): SessionDetailRecord {
  return {
    session: mapSessionSummary(detail),
    collectionId: detail.collectionId,
    messages: detail.messages.map(mapSessionMessage),
  };
}

function normalizeCollectionId(collectionId: string | null | undefined, collections: CollectionSummary[]) {
  if (collectionId && collections.some((collection) => collection.id === collectionId)) {
    return collectionId;
  }

  return ROOT_COLLECTION.id;
}

function buildCollections(topics: TopicSummaryApiResponse[]): CollectionSummary[] {
  return [ROOT_COLLECTION, ...topics.map((topic) => ({ id: topic.id, label: topic.label }))];
}

function mapKnowledgeGraph(graph: GraphApiResponse): KnowledgeGraph {
  return {
    nodes: graph.nodes.map((node) => ({
      id: node.id,
      label: node.label,
      chunkCount: node.chunkCount,
      documentCount: node.documentCount,
      keywords: node.keywords ?? [],
      sourceDocuments: node.sourceDocuments ?? [],
      pageKeys: node.pageKeys ?? [],
    })),
    edges: graph.edges.map((edge) => ({
      source: edge.source,
      target: edge.target,
      weight: edge.weight,
      directed: edge.directed ?? true,
      semanticScore: edge.semanticScore,
      pageOverlapScore: edge.pageOverlapScore,
      documentOverlapScore: edge.documentOverlapScore,
      sharedPages: edge.sharedPages ?? [],
      sharedDocuments: edge.sharedDocuments ?? [],
      reason: edge.reason,
    })),
  };
}

export const httpWorkbenchGateway = {
  async loadKnowledgeBase(): Promise<KnowledgeBaseRecord> {
    const [documents, topics, graph] = await Promise.all([
      requestJson<IndexedDocumentApiResponse[]>("/api/documents"),
      requestJson<TopicSummaryApiResponse[]>("/api/topics"),
      requestJson<GraphApiResponse>("/api/kg/graph"),
    ]);

    const pipelineDocuments = documents.map(mapIndexedDocument);
    const indexedChunks = pipelineDocuments.reduce((total, document) => total + document.chunkCount, 0);

    return {
      collections: buildCollections(topics),
      pipelineDocuments,
      knowledgeGraph: mapKnowledgeGraph(graph),
      knowledgeBaseSummary: {
        indexedDocuments: pipelineDocuments.length,
        indexedChunks,
        uploadHint:
          "Drop PDFs into the pipeline to queue background indexing. Chat and pipeline state stay synchronized automatically.",
      },
    };
  },

  async bootstrap(): Promise<BootstrapPayload> {
    const [knowledgeBase, existingSessions, health] = await Promise.all([
      this.loadKnowledgeBase(),
      requestJson<SessionSummaryApiResponse[]>("/api/sessions"),
      requestJson<{ thinkingSupported: boolean }>("/api/system/health"),
    ]);

    let activeSessionDetail: SessionDetailRecord;
    let sessions = existingSessions;

    if (sessions.length === 0) {
      activeSessionDetail = await this.createSession(ROOT_COLLECTION.id);
      sessions = [
        {
          id: activeSessionDetail.session.id,
          title: activeSessionDetail.session.title,
          group: activeSessionDetail.session.group,
          collectionId: activeSessionDetail.collectionId,
          updatedAt: new Date().toISOString(),
        },
      ];
    } else {
      activeSessionDetail = await this.getSession(sessions[0].id);
    }

    return {
      sessions: sessions.map(mapSessionSummary),
      activeSessionId: activeSessionDetail.session.id,
      collections: knowledgeBase.collections,
      activeCollectionId: normalizeCollectionId(
        activeSessionDetail.collectionId,
        knowledgeBase.collections,
      ),
      messagesBySession: {
        [activeSessionDetail.session.id]: activeSessionDetail.messages,
      },
      pipelineDocuments: knowledgeBase.pipelineDocuments,
      knowledgeGraph: knowledgeBase.knowledgeGraph,
      knowledgeBaseSummary: knowledgeBase.knowledgeBaseSummary,
      thinkingSupported: health.thinkingSupported,
    };
  },

  async listSessions(): Promise<SessionSummary[]> {
    const sessions = await requestJson<SessionSummaryApiResponse[]>("/api/sessions");
    return sessions.map(mapSessionSummary);
  },

  async createSession(collectionId: string): Promise<SessionDetailRecord> {
    const detail = await requestJson<SessionDetailApiResponse>("/api/sessions", {
      method: "POST",
      headers: buildHeaders({
        "Content-Type": "application/json",
      }),
      body: JSON.stringify({ collectionId } satisfies CreateSessionApiRequest),
    });

    return mapSessionDetail(detail);
  },

  async getSession(sessionId: string): Promise<SessionDetailRecord> {
    const detail = await requestJson<SessionDetailApiResponse>(`/api/sessions/${sessionId}`);
    return mapSessionDetail(detail);
  },

  async deleteSession(sessionId: string): Promise<void> {
    await requestNoContent(`/api/sessions/${sessionId}`, {
      method: "DELETE",
    });
  },

  async reclusterTopics(): Promise<ReclusterApiResponse> {
    return requestJson<ReclusterApiResponse>("/api/topics/recluster", {
      method: "POST",
    });
  },

  async uploadDocuments(files: File[]): Promise<KnowledgeBaseRecord> {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append("files", file, file.name);
    });

    const response = await fetch(`${API_BASE_URL}/api/documents/upload`, {
      method: "POST",
      headers: buildHeaders(),
      body: formData,
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail ?? `Upload failed with status ${response.status}.`);
    }

    return this.loadKnowledgeBase();
  },

  async deleteDocument(documentId: string): Promise<void> {
    await requestNoContent(`/api/documents/${documentId}`, {
      method: "DELETE",
    });
  },

  subscribeIngestionProgress(
    callback: (event: IngestionProgressEvent) => void,
    onDisconnect?: () => void,
  ): () => void {
    const abortController = new AbortController();

    void (async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/events/ingestion-progress`, {
          headers: buildHeaders({
            Accept: "text/event-stream",
          }),
          signal: abortController.signal,
        });
        if (!response.ok) {
          throw new Error(`Ingestion progress stream failed with status ${response.status}.`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("The browser could not read the ingestion progress stream.");
        }

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { value, done } = await reader.read();
          buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

          const chunk = readSseEvents(buffer);
          buffer = chunk.remaining;
          for (const rawEvent of chunk.events) {
            const payload = parseSsePayload<IngestionProgressApiResponse>(rawEvent);
            if (payload) {
              callback(payload);
            }
          }

          if (done) {
            const payload = parseSsePayload<IngestionProgressApiResponse>(buffer);
            if (payload) {
              callback(payload);
            }
            break;
          }
        }

        if (!abortController.signal.aborted) {
          onDisconnect?.();
        }
      } catch {
        if (!abortController.signal.aborted) {
          onDisconnect?.();
        }
      }
    })();

    return () => {
      abortController.abort();
    };
  },

  async streamMessage(
    input: SendMessageInput,
    handlers: StreamHandlers,
    options?: StreamRequestOptions,
  ): Promise<StreamMessageResult> {
    const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
      method: "POST",
      headers: buildHeaders({
        "Content-Type": "application/json",
      }),
      signal: options?.signal,
      body: JSON.stringify({
        message: input.text,
        collectionId: input.collectionId,
        sessionId: input.sessionId,
        webSearchEnabled: Boolean(input.webSearchEnabled),
        thinkingEnabled: Boolean(input.thinkingEnabled),
        responseLength: input.responseLength,
        images: input.images,
      }),
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail ?? `Chat stream failed with status ${response.status}.`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("The browser could not read the chat stream.");
    }

    const decoder = new TextDecoder();
    let buffer = "";
    let finalPayload: StreamDonePayload | null = null;
    let offlineWarning: string | null = null;

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

      const chunk = readSseEvents(buffer);
      buffer = chunk.remaining;
      for (const rawEvent of chunk.events) {
        const payload = parseSsePayload<StreamPayload>(rawEvent);

        if (payload?.type === "token") {
          handlers.onToken(payload.delta);
        }

        if (payload?.type === "done") {
          finalPayload = payload;
          offlineWarning = payload.offlineWarning ?? offlineWarning;
        }

        if (payload?.type === "tool") {
          offlineWarning = payload.offlineWarning ?? offlineWarning;
          handlers.onTool(payload.toolCall, payload.offlineWarning);
        }

        if (payload?.type === "error") {
          throw new Error(payload.message);
        }
      }

      if (done) {
        const payload = parseSsePayload<StreamPayload>(buffer);
        if (payload?.type === "token") {
          handlers.onToken(payload.delta);
        }
        if (payload?.type === "done") {
          finalPayload = payload;
          offlineWarning = payload.offlineWarning ?? offlineWarning;
        }
        if (payload?.type === "tool") {
          offlineWarning = payload.offlineWarning ?? offlineWarning;
          handlers.onTool(payload.toolCall, payload.offlineWarning);
        }
        if (payload?.type === "error") {
          throw new Error(payload.message);
        }
        break;
      }
    }

    if (!finalPayload) {
      throw new Error("The assistant stream finished without a completion event.");
    }

    return {
      message: {
        id: `assistant-${crypto.randomUUID()}`,
        role: "assistant",
        content: finalPayload.answer,
        status: "complete",
        citations: finalPayload.citations.map(mapCitation),
        answerTrace: finalPayload.answerTrace ?? [],
        modelThinking: finalPayload.modelThinking ?? undefined,
        thinkingRequested: finalPayload.thinkingRequested ?? input.thinkingEnabled,
        collectionId: finalPayload.collectionId ?? input.collectionId,
        collectionLabel: finalPayload.collectionLabel ?? input.collectionId,
        crossSessionMemoryUsed: finalPayload.crossSessionMemoryUsed ?? 0,
        toolCall: finalPayload.toolCall ?? undefined,
        webSearchRequested: finalPayload.webSearchRequested ?? input.webSearchEnabled,
        webSearchUsed: finalPayload.webSearchUsed ?? false,
        offlineWarning: finalPayload.offlineWarning ?? undefined,
        sessionWarning: finalPayload.sessionWarning ?? undefined,
      },
      offlineWarning,
      sessionTitle: finalPayload.sessionTitle ?? undefined,
    };
  },

  async getPdfPreview(request: PdfPreviewRequest): Promise<PdfPreview> {
    const chunkIndex = request.chunkIndex ?? 0;
    const previewUrl = new URL(`${API_BASE_URL}/api/documents/preview`);
    previewUrl.searchParams.set("pdfName", request.pdfName);
    previewUrl.searchParams.set("page", String(request.page));
    previewUrl.searchParams.set("chunkIndex", String(chunkIndex));

    const response = await fetch(previewUrl, {
      headers: buildHeaders(),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail ?? `Preview request failed with status ${response.status}.`);
    }

    const payload = (await response.json()) as PreviewApiResponse;
    return {
      id: `${payload.pdfName}:${payload.page}:${chunkIndex}`,
      pdfName: payload.pdfName,
      page: payload.page,
      totalPages: payload.totalPages,
      chunkIndex,
      htmlContent: payload.htmlContent,
      fileUrl: payload.fileUrl ? new URL(payload.fileUrl, API_BASE_URL).toString() : undefined,
    };
  },

  resolveErrorMessage,
  isAbortError,
};
