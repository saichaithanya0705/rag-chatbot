import assert from "node:assert/strict";
import test from "node:test";
import { httpWorkbenchGateway } from "../src/shared/api/httpWorkbench";

const BACKEND_STARTING_DETAIL = "The service is still starting up. Try again shortly.";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
    },
  });
}

test("bootstrap waits for backend readiness before loading workspace data", async () => {
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  const responses = [
    jsonResponse({ detail: BACKEND_STARTING_DETAIL }, 503),
    jsonResponse({ status: "ok" }),
    jsonResponse({ status: "ok", thinkingSupported: true }),
    jsonResponse([]),
    jsonResponse([]),
    jsonResponse({ nodes: [], edges: [] }),
    jsonResponse([]),
    jsonResponse({
      id: "session-1",
      title: "New chat",
      group: "Today",
      collectionId: "all-pdfs",
      updatedAt: "2026-06-12T13:30:00Z",
      messages: [],
    }),
  ];

  globalThis.fetch = async (input: string | URL | Request) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    calls.push(url);
    const response = responses.shift();
    assert.ok(response, `Unexpected fetch: ${url}`);
    return response;
  };

  try {
    const payload = await httpWorkbenchGateway.bootstrap();

    assert.equal(payload.activeSessionId, "session-1");
    assert.equal(payload.pipelineDocuments.length, 0);
    assert.equal(payload.thinkingSupported, true);
    assert.deepEqual(
      calls.map((url) => new URL(url).pathname),
      [
        "/api/system/ready",
        "/api/system/ready",
        "/api/system/health",
        "/api/documents",
        "/api/topics",
        "/api/kg/graph",
        "/api/sessions",
        "/api/sessions",
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("bootstrap retries transient startup responses instead of failing permanently", async () => {
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  const responses = [
    jsonResponse({ status: "ok" }),
    jsonResponse({ status: "ok", thinkingSupported: true }),
    jsonResponse({ detail: BACKEND_STARTING_DETAIL }, 503),
    jsonResponse([]),
    jsonResponse({ nodes: [], edges: [] }),
    jsonResponse([
      {
        id: "session-1",
        title: "Existing session",
        group: "Today",
        collectionId: "all-pdfs",
        updatedAt: "2026-06-12T13:31:00Z",
      },
    ]),
    jsonResponse({ status: "ok" }),
    jsonResponse({ status: "ok", thinkingSupported: true }),
    jsonResponse([]),
    jsonResponse([]),
    jsonResponse({ nodes: [], edges: [] }),
    jsonResponse([
      {
        id: "session-1",
        title: "Existing session",
        group: "Today",
        collectionId: "all-pdfs",
        updatedAt: "2026-06-12T13:31:00Z",
      },
    ]),
    jsonResponse({
      id: "session-1",
      title: "Existing session",
      group: "Today",
      collectionId: "all-pdfs",
      updatedAt: "2026-06-12T13:31:00Z",
      messages: [],
    }),
  ];

  globalThis.fetch = async (input: string | URL | Request) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    calls.push(url);
    const response = responses.shift();
    assert.ok(response, `Unexpected fetch: ${url}`);
    return response;
  };

  try {
    const payload = await httpWorkbenchGateway.bootstrap();

    assert.equal(payload.activeSessionId, "session-1");
    assert.equal(payload.sessions.length, 1);
    assert.equal(payload.thinkingSupported, true);
    assert.equal(
      calls.filter((url) => new URL(url).pathname === "/api/system/ready").length,
      2,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
