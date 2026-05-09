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
  assert.match(html, /<code>spaced repetition<\/code>/);
  assert.match(html, /<ol>/);
  assert.match(html, /<table>/);
  assert.match(html, /<pre><code class="language-ts">const ready = true;\n?<\/code><\/pre>/);
});

test("escapes raw html from model output instead of executing it", () => {
  const html = renderToStaticMarkup(<MessageMarkdown content={'<img src=x onerror="alert(1)" />'} />);

  assert.doesNotMatch(html, /<img/i);
  assert.match(html, /&lt;img src=x onerror=&quot;alert\(1\)&quot; \/&gt;/);
});
