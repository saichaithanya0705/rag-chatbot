import assert from "node:assert/strict";
import { test } from "node:test";
import { validateProductionApiBaseUrl } from "../vite.config";

test("production builds require an API base URL", () => {
  assert.throws(
    () => validateProductionApiBaseUrl("production", undefined),
    /VITE_API_BASE_URL is required/,
  );
});

test("production builds reject malformed and loopback API URLs", () => {
  assert.throws(
    () => validateProductionApiBaseUrl("production", "not-a-url"),
    /valid absolute HTTP\(S\) URL/,
  );
  assert.throws(
    () => validateProductionApiBaseUrl("production", "http://localhost:8000"),
    /must not target a loopback host/,
  );
});

test("production builds accept the public HTTPS backend and development may use defaults", () => {
  assert.doesNotThrow(() =>
    validateProductionApiBaseUrl(
      "production",
      "https://rag-chatbot-api-0612.onrender.com",
    ),
  );
  assert.doesNotThrow(() => validateProductionApiBaseUrl("development", undefined));
});
