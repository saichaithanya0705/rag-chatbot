import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MessageMarkdown } from "../src/shared/ui/message-markdown/MessageMarkdown";

test("renders assistant markdown with common chat formatting", () => {
  const html = renderToStaticMarkup(
    <MessageMarkdown
      content={[
        "# Study plan",
        "",
        "Use **active recall** and `spaced repetition`.",
        "",
        "1. Read the notes",
        "2. Make flashcards",
        "",
        "| Topic | Priority |",
        "| --- | --- |",
        "| DBMS | High |",
        "",
        "```ts",
        "const ready = true;",
        "```",
      ].join("\n")}
    />,
  );

  assert.match(html, /<h1>Study plan<\/h1>/);
  assert.match(html, /<strong>active recall<\/strong>/);
  assert.match(html, /<code[^>]*>spaced repetition<\/code>/);
  assert.match(html, /<ol>/);
  assert.match(html, /<table[^>]*>/);
  assert.match(html, /const ready = true;/);
});

test("escapes raw html from model output instead of executing it", () => {
  const html = renderToStaticMarkup(<MessageMarkdown content={'<img src=x onerror="alert(1)" />'} />);

  assert.doesNotMatch(html, /<img/i);
  assert.match(html, /&lt;img src=x onerror=&quot;alert\(1\)&quot; \/&gt;/);
});

test("renders inline citation badges with proper index and accessibility label", () => {
  const html = renderToStaticMarkup(
    <MessageMarkdown
      content="According to the research [SourceID: ref-1], surgical outcomes improved."
      citations={[
        {
          id: "ref-1",
          kind: "pdf",
          pdfName: "Bailey and Love",
          page: 42,
          excerpt: "Surgical outcomes showed significant improvement.",
        },
      ]}
    />,
  );

  assert.match(html, /\[1\]/);
  assert.match(html, /aria-label="Source citation 1: Bailey and Love"/);
});

