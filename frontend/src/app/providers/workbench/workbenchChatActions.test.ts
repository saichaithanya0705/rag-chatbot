/// <reference types="node" />

import assert from "node:assert/strict";
import { test } from "node:test";
import { httpWorkbenchGateway } from "../../../shared/api/httpWorkbench";
import type { SendMessageInput, StreamMessageResult } from "../../../shared/api/types";
import { createInitialWorkbenchState } from "./workbenchInitialState";
import { createWorkbenchChatActions } from "./workbenchChatActions";
import type { WorkbenchState } from "./workbenchTypes";

function createWorkbenchState(overrides: Partial<WorkbenchState> = {}): WorkbenchState {
  return {
    ...createInitialWorkbenchState(),
    isBootstrapping: false,
    sessions: [{ id: "session-1", title: "Existing chat", group: "Today" }],
    activeSessionId: "session-1",
    collections: [{ id: "all-pdfs", label: "All PDFs" }],
    activeCollectionId: "all-pdfs",
    messagesBySession: { "session-1": [] },
    thinkingSupported: true,
    ...overrides,
  };
}

function createHarness(initialState: WorkbenchState) {
  let currentState = initialState;
  const toastMessages: string[] = [];
  const refreshedSessions: Array<string | undefined> = [];
  const scheduledTitleRefreshes: string[] = [];

  const sendInFlightRef = { current: false };
  const activeChatAbortControllerRef = { current: null as AbortController | null };
  const thinkingEnabledRef = { current: currentState.thinkingEnabled };
  const detailedAnswerEnabledRef = { current: currentState.detailedAnswerEnabled };
  const titleSyncTimeoutRef = { current: new Map<string, number>() };

  const actions = createWorkbenchChatActions({
    state: currentState,
    setState: (nextState) => {
      currentState =
        typeof nextState === "function" ? nextState(currentState) : nextState;
    },
    sendInFlightRef,
    activeChatAbortControllerRef,
    thinkingEnabledRef,
    detailedAnswerEnabledRef,
    titleSyncTimeoutRef,
    showToast: (message) => {
      toastMessages.push(message);
    },
    refreshSessions: async (preferredSessionId) => {
      refreshedSessions.push(preferredSessionId);
    },
    scheduleSessionTitleRefresh: (sessionId) => {
      scheduledTitleRefreshes.push(sessionId);
    },
  });

  return {
    actions,
    getState: () => currentState,
    toastMessages,
    refreshedSessions,
    scheduledTitleRefreshes,
    sendInFlightRef,
    activeChatAbortControllerRef,
  };
}

function makeAbortError() {
  const error = new Error("The operation was aborted.");
  error.name = "AbortError";
  return error;
}

test("sendMessage allows image-only prompts and keeps the workbench session in sync", async () => {
  const initialState = createWorkbenchState({
    draftImages: [{ data: "abc123", mimeType: "image/png", url: "data:image/png;base64,abc123" }],
  });
  const harness = createHarness(initialState);

  const originalStreamMessage = httpWorkbenchGateway.streamMessage;
  const originalResolveErrorMessage = httpWorkbenchGateway.resolveErrorMessage;
  const originalIsAbortError = httpWorkbenchGateway.isAbortError;
  let receivedInput: SendMessageInput | null = null;

  httpWorkbenchGateway.streamMessage = async (input: SendMessageInput): Promise<StreamMessageResult> => {
    receivedInput = input;
    return {
      message: {
        id: "assistant-final",
        role: "assistant",
        content: "Processed the image.",
        status: "complete",
        citations: [],
      },
      offlineWarning: null,
      sessionTitle: "Vision chat",
    };
  };
  httpWorkbenchGateway.resolveErrorMessage = originalResolveErrorMessage;
  httpWorkbenchGateway.isAbortError = originalIsAbortError;

  try {
    await harness.actions.sendMessage("   ");
  } finally {
    httpWorkbenchGateway.streamMessage = originalStreamMessage;
    httpWorkbenchGateway.resolveErrorMessage = originalResolveErrorMessage;
    httpWorkbenchGateway.isAbortError = originalIsAbortError;
  }

  if (receivedInput === null) {
    throw new Error("Expected sendMessage to call streamMessage with input.");
  }
  const actualInput = receivedInput as SendMessageInput;
  assert.equal(actualInput.text, "");
  assert.equal(actualInput.images?.length, 1);
  assert.equal(harness.getState().messagesBySession["session-1"].length, 2);
  assert.equal(harness.getState().messagesBySession["session-1"][0].content, "");
  assert.equal(harness.getState().messagesBySession["session-1"][0].images?.length, 1);
  assert.equal(harness.getState().messagesBySession["session-1"][1].content, "Processed the image.");
  assert.equal(harness.getState().draftImages.length, 0);
  assert.equal(harness.getState().isSendingMessage, false);
  assert.deepEqual(harness.refreshedSessions, ["session-1"]);
  assert.equal(harness.activeChatAbortControllerRef.current, null);
});

test("stopMessage aborts streaming and restores the optimistic draft state", async () => {
  const initialState = createWorkbenchState({
    draftMessage: "Describe this image",
    draftImages: [{ data: "xyz987", mimeType: "image/png", url: "data:image/png;base64,xyz987" }],
  });
  const harness = createHarness(initialState);

  const originalStreamMessage = httpWorkbenchGateway.streamMessage;
  const originalResolveErrorMessage = httpWorkbenchGateway.resolveErrorMessage;
  const originalIsAbortError = httpWorkbenchGateway.isAbortError;

  httpWorkbenchGateway.streamMessage = async (_input, _handlers, options) =>
    new Promise<StreamMessageResult>((_resolve, reject) => {
      options?.signal?.addEventListener(
        "abort",
        () => {
          reject(makeAbortError());
        },
        { once: true },
      );
    });
  httpWorkbenchGateway.resolveErrorMessage = originalResolveErrorMessage;
  httpWorkbenchGateway.isAbortError = (error) => error instanceof Error && error.name === "AbortError";

  try {
    const pendingSend = harness.actions.sendMessage(initialState.draftMessage);

    assert.equal(harness.getState().isSendingMessage, true);
    assert.equal(harness.getState().messagesBySession["session-1"].length, 2);

    harness.actions.stopMessage();
    await pendingSend;
  } finally {
    httpWorkbenchGateway.streamMessage = originalStreamMessage;
    httpWorkbenchGateway.resolveErrorMessage = originalResolveErrorMessage;
    httpWorkbenchGateway.isAbortError = originalIsAbortError;
  }

  assert.equal(harness.getState().isSendingMessage, false);
  assert.equal(harness.getState().draftMessage, "Describe this image");
  assert.equal(harness.getState().draftImages.length, 1);
  assert.deepEqual(harness.getState().messagesBySession["session-1"], []);
  assert.deepEqual(harness.toastMessages, ["Response stopped. Your draft was restored."]);
  assert.equal(harness.sendInFlightRef.current, false);
  assert.equal(harness.activeChatAbortControllerRef.current, null);
});
