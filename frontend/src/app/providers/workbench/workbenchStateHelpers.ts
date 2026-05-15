import type {
  Citation,
  CollectionSummary,
  Message,
  PdfPreviewRequest,
  PipelineDocument,
  PipelineStatus,
} from "@/shared/api/types";

export const ROOT_COLLECTION_ID = "all-pdfs";

export function toPreviewRequest(citation: Citation): PdfPreviewRequest {
  if (citation.kind !== "pdf" || !citation.pdfName || citation.page === undefined) {
    throw new Error("Only PDF citations can open the preview panel.");
  }

  return {
    pdfName: citation.pdfName,
    page: citation.page,
    chunkIndex: citation.chunkIndex ?? 0,
    excerpt: citation.sourceText ?? citation.excerpt,
  };
}

export function appendMessages(
  messageMap: Record<string, Message[]>,
  sessionId: string,
  nextMessages: Message[],
) {
  return {
    ...messageMap,
    [sessionId]: [...(messageMap[sessionId] ?? []), ...nextMessages],
  };
}

export function replaceMessage(
  messageMap: Record<string, Message[]>,
  sessionId: string,
  targetId: string,
  nextMessage: Message,
) {
  return {
    ...messageMap,
    [sessionId]: (messageMap[sessionId] ?? []).map((message) =>
      message.id === targetId ? nextMessage : message,
    ),
  };
}

export function updateMessageContent(
  messageMap: Record<string, Message[]>,
  sessionId: string,
  targetId: string,
  nextContent: string,
) {
  return {
    ...messageMap,
    [sessionId]: (messageMap[sessionId] ?? []).map((message) =>
      message.id === targetId
        ? {
            ...message,
            content: nextContent,
          }
        : message,
    ),
  };
}

export function updateMessage(
  messageMap: Record<string, Message[]>,
  sessionId: string,
  targetId: string,
  updater: (message: Message) => Message,
) {
  return {
    ...messageMap,
    [sessionId]: (messageMap[sessionId] ?? []).map((message) =>
      message.id === targetId ? updater(message) : message,
    ),
  };
}

export function retainKnownSessionMessages(
  messageMap: Record<string, Message[]>,
  sessionIds: string[],
) {
  const knownSessionIds = new Set(sessionIds);
  return Object.fromEntries(
    Object.entries(messageMap).filter(([sessionId]) => knownSessionIds.has(sessionId)),
  );
}

export function normalizeCollectionId(
  collections: CollectionSummary[],
  collectionId: string | null | undefined,
) {
  if (collectionId && collections.some((collection) => collection.id === collectionId)) {
    return collectionId;
  }

  return ROOT_COLLECTION_ID;
}

export function resolveCollectionLabel(collections: CollectionSummary[], collectionId: string) {
  return collections.find((collection) => collection.id === collectionId)?.label ?? "All PDFs";
}

export function buildPendingAnswerTrace(collectionLabel: string, webSearchRequested: boolean) {
  return [
    {
      kind: "scope",
      label: "Scope",
      detail: `Scoped this answer to ${collectionLabel}. Live web lookup was ${
        webSearchRequested ? "enabled" : "off"
      } for this turn.`,
    },
  ] satisfies NonNullable<Message["answerTrace"]>;
}

export function toStatusMap(documents: PipelineDocument[]) {
  return Object.fromEntries(documents.map((document) => [document.id, document.status])) as Record<
    string,
    PipelineStatus
  >;
}
