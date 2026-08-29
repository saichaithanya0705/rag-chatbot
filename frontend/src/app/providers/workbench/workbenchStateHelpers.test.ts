/// <reference types="node" />

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Message, PipelineDocument } from "../../../shared/api/types";
import {
  appendMessages,
  buildPendingAnswerTrace,
  hasDraftSubmissionContent,
  normalizeCollectionId,
  removeMessages,
  replaceMessage,
  resolveCollectionLabel,
  retainKnownSessionMessages,
  toPreviewRequest,
  toStatusMap,
  updateMessageContent,
} from "./workbenchStateHelpers";
import {
  createInitialWorkbenchState,
  getInitialCompactViewport,
  getInitialThinkingEnabled,
  persistThinkingEnabled,
  THINKING_ENABLED_STORAGE_KEY,
} from "./workbenchInitialState";
import { makeWorkbenchActionProxy, WORKBENCH_ACTION_KEYS } from "./workbenchActions";
import type { WorkbenchActions } from "./workbenchTypes";

const originalWindow = globalThis.window;

function restoreWindow() {
  if (originalWindow === undefined) {
    Reflect.deleteProperty(globalThis, "window");
    return;
  }

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: originalWindow,
  });
}

function clearWindow() {
  Reflect.deleteProperty(globalThis, "window");
}

function installMockWindow(options: { matchesCompactViewport: boolean; storedThinking?: string }) {
  const storage = new Map<string, string>();
  if (options.storedThinking !== undefined) {
    storage.set(THINKING_ENABLED_STORAGE_KEY, options.storedThinking);
  }

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      matchMedia: (query: string) => ({
        matches: options.matchesCompactViewport,
        media: query,
      }),
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => storage.set(key, value),
      },
    },
  });

  return storage;
}

function makeMessage(overrides: Partial<Message>): Message {
  return {
    id: "message-1",
    role: "assistant",
    content: "Original",
    status: "complete",
    citations: [],
    ...overrides,
  };
}

test("message map helpers update targeted messages without mutating the previous map", () => {
  const firstMessage = makeMessage({ id: "assistant-1", content: "Thinking..." });
  const messageMap: Record<string, Message[]> = {
    sessionA: [firstMessage],
    sessionB: [makeMessage({ id: "assistant-2", content: "Untouched" })],
  };

  const appended = appendMessages(messageMap, "sessionA", [
    makeMessage({ id: "assistant-3", content: "Next" }),
  ]);
  assert.deepEqual(
    appended.sessionA.map((message) => message.id),
    ["assistant-1", "assistant-3"],
  );
  assert.deepEqual(
    messageMap.sessionA.map((message) => message.id),
    ["assistant-1"],
  );

  const replaced = replaceMessage(
    appended,
    "sessionA",
    "assistant-1",
    makeMessage({ id: "assistant-1", content: "Complete" }),
  );
  assert.equal(replaced.sessionA[0].content, "Complete");
  assert.equal(appended.sessionA[0].content, "Thinking...");

  const streamed = updateMessageContent(replaced, "sessionA", "assistant-3", "Streaming");
  assert.equal(streamed.sessionA[1].content, "Streaming");
  assert.equal(streamed.sessionB[0].content, "Untouched");

  const removed = removeMessages(streamed, "sessionA", ["assistant-1"]);
  assert.deepEqual(
    removed.sessionA.map((message) => message.id),
    ["assistant-3"],
  );
  assert.deepEqual(
    streamed.sessionA.map((message) => message.id),
    ["assistant-1", "assistant-3"],
  );
});

test("collection helpers normalize unknown scopes and keep known scope labels", () => {
  const collections = [
    { id: "all-pdfs", label: "All PDFs" },
    { id: "topic-a", label: "Topic A" },
  ];

  assert.equal(normalizeCollectionId(collections, "topic-a"), "topic-a");
  assert.equal(normalizeCollectionId(collections, "missing"), "all-pdfs");
  assert.equal(normalizeCollectionId(collections, null), "all-pdfs");
  assert.equal(resolveCollectionLabel(collections, "topic-a"), "Topic A");
  assert.equal(resolveCollectionLabel(collections, "missing"), "All PDFs");
  assert.equal(hasDraftSubmissionContent("Question", 0), true);
  assert.equal(hasDraftSubmissionContent("   ", 1), true);
  assert.equal(hasDraftSubmissionContent("   ", 0), false);
  assert.match(buildPendingAnswerTrace("Topic A", true)[0].detail, /Live web lookup was enabled/);
});

test("preview and pipeline helpers preserve request and status mapping behavior", () => {
  assert.deepEqual(
    toPreviewRequest({
      id: "citation-1",
      kind: "pdf",
      pdfName: "paper.pdf",
      page: 4,
      chunkIndex: 2,
      excerpt: "excerpt",
      sourceText: "source text",
    }),
    {
      pdfName: "paper.pdf",
      page: 4,
      chunkIndex: 2,
      excerpt: "source text",
    },
  );
  assert.throws(() => toPreviewRequest({ id: "citation-2", kind: "web" }), /Only PDF citations/);

  const documents = [
    { id: "doc-1", status: "queued" },
    { id: "doc-2", status: "indexed" },
  ] as PipelineDocument[];
  assert.deepEqual(toStatusMap(documents), {
    "doc-1": "queued",
    "doc-2": "indexed",
  });
});

test("session message retention drops messages for sessions no longer listed", () => {
  const retained = retainKnownSessionMessages(
    {
      sessionA: [makeMessage({ id: "assistant-1" })],
      sessionB: [makeMessage({ id: "assistant-2" })],
    },
    ["sessionB"],
  );

  assert.deepEqual(Object.keys(retained), ["sessionB"]);
});

test("initial workbench state derives viewport and thinking preferences from browser storage", () => {
  const storage = installMockWindow({
    matchesCompactViewport: true,
    storedThinking: "false",
  });

  try {
    assert.equal(getInitialCompactViewport(), true);
    assert.equal(getInitialThinkingEnabled(), false);

    const state = createInitialWorkbenchState();
    assert.equal(state.isBootstrapping, true);
    assert.equal(state.isCompactViewport, true);
    assert.equal(state.sidebarOpen, false);
    assert.equal(state.thinkingEnabled, false);
    assert.deepEqual(state.knowledgeGraph, { nodes: [], edges: [] });
    assert.deepEqual(state.knowledgeBaseSummary, {
      indexedDocuments: 0,
      indexedChunks: 0,
      uploadHint: "",
    });

    persistThinkingEnabled(true);
    assert.equal(storage.get(THINKING_ENABLED_STORAGE_KEY), "true");
  } finally {
    restoreWindow();
  }
});

test("stable workbench action proxy delegates to the latest action ref", async () => {
  const calls: string[] = [];
  const makeActions = (label: string): WorkbenchActions => ({
    retryBootstrap: async () => {
      calls.push(`${label}:retryBootstrap`);
    },
    createSession: async () => {
      calls.push(`${label}:createSession`);
    },
    selectSession: async (sessionId) => {
      calls.push(`${label}:selectSession:${sessionId}`);
    },
    deleteSession: async (sessionId) => {
      calls.push(`${label}:deleteSession:${sessionId}`);
    },
    toggleSidebar: () => calls.push(`${label}:toggleSidebar`),
    setSidebarOpen: (nextValue) => calls.push(`${label}:setSidebarOpen:${nextValue}`),
    selectCollection: (collectionId) => calls.push(`${label}:selectCollection:${collectionId}`),
    setDraftMessage: (nextValue) => calls.push(`${label}:setDraftMessage:${nextValue}`),
    toggleWebSearch: () => calls.push(`${label}:toggleWebSearch`),
    toggleThinking: () => calls.push(`${label}:toggleThinking`),
    toggleDetailedAnswer: () => calls.push(`${label}:toggleDetailedAnswer`),
    sendMessage: async (text) => {
      calls.push(`${label}:sendMessage:${text}`);
    },
    stopMessage: () => {
      calls.push(`${label}:stopMessage`);
    },
    openPdfPreview: async (citation) => {
      calls.push(`${label}:openPdfPreview:${citation.id}`);
    },
    goToPdfPreviewPage: async (page) => {
      calls.push(`${label}:goToPdfPreviewPage:${page}`);
    },
    retryPdfPreview: async () => {
      calls.push(`${label}:retryPdfPreview`);
    },
    closePdfPreview: () => calls.push(`${label}:closePdfPreview`),
    uploadDocuments: async (files) => {
      calls.push(`${label}:uploadDocuments:${files.length}`);
    },
    reclusterTopics: async () => {
      calls.push(`${label}:reclusterTopics`);
    },
    removePipelineDocument: async (documentId) => {
      calls.push(`${label}:removePipelineDocument:${documentId}`);
    },
    clearToast: () => calls.push(`${label}:clearToast`),
    addDraftImage: (image) => {
      calls.push(`${label}:addDraftImage:${image.url}`);
    },
    removeDraftImage: (index) => {
      calls.push(`${label}:removeDraftImage:${index}`);
    },
    clearDraftImages: () => {
      calls.push(`${label}:clearDraftImages`);
    },
    toggleTheme: () => {
      calls.push(`${label}:toggleTheme`);
    },
  });
  const actionRef = { current: makeActions("initial") };
  const proxy = makeWorkbenchActionProxy(actionRef);

  assert.deepEqual(Object.keys(proxy), WORKBENCH_ACTION_KEYS);

  actionRef.current = makeActions("latest");
  proxy.toggleSidebar();
  proxy.stopMessage();
  await proxy.selectSession("session-1");

  assert.deepEqual(calls, ["latest:toggleSidebar", "latest:stopMessage", "latest:selectSession:session-1"]);
});
