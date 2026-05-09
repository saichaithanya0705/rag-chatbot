# UI Issues Checklist

Generated from code review of `frontend/src/` on 2026-04-05.

---

## Critical Bugs

- [ ] **1. CSS class mismatch in ChatComposer** — `ChatComposer.tsx` renders `styles.inputLabelRow`, `styles.inputLabel`, and `styles.inputScope` but `chat-view.module.css` only defines `.composerMeta` and `.composerLabel`. The composer label row ("Ask the assistant" / "Scope: …") renders with no styles at all.
  - File: `frontend/src/widgets/chat-shell/ChatComposer.tsx:43-48`
  - Fix: rename `.composerMeta → .inputLabelRow`, `.composerLabel → .inputLabel`; add `.inputScope`

- [ ] **2. Code inline-block uses a text color token as a background** — `.bubble code { background: var(--text-subtle-aa) }` uses `--text-subtle-aa` (`#736e64`, a dark brownish text color) as a background. Inline code in bot messages renders with a dark mud background.
  - File: `frontend/src/widgets/chat-shell/message-thread.module.css:64-67`
  - Fix: change to `background: var(--surface-soft)` or `var(--surface-muted)`

---

## Usability Issues

- [ ] **3. No "New Chat" shortcut without opening the sidebar** — The only way to create a new session is to toggle the sidebar panel open. The topbar has no quick-action button for this, adding an unnecessary step.
  - File: `frontend/src/widgets/chat-shell/ChatView.tsx` (topbar section)
  - Fix: add a "New chat" icon button to the chat topbar, calling `actions.createSession()`

- [ ] **4. No cancel/stop button during message sending** — Once a message is sent (`isSendingMessage = true`), the send button switches to a loading animation with no way to abort. Users have no escape hatch if a request hangs.
  - File: `frontend/src/widgets/chat-shell/ChatComposer.tsx:66-83`
  - Fix: when `isMessagePending`, show a stop/cancel icon button that calls a cancel action

- [ ] **5. Drop zone missing accessible name** — In `PipelineView.tsx`, the upload drop zone has `role="button"` and `tabIndex={0}` but no `aria-label`. Screen readers and keyboard users have no context for what this interactive region does.
  - File: `frontend/src/widgets/pipeline-shell/PipelineView.tsx:430-455`
  - Fix: add `aria-label="Upload PDF files"` to the drop zone div

- [ ] **6. Collection label and dropdown are separate flex items** — In the chat topbar, the `<span class="collectionLabel">Collection</span>` and its `<div class="collectionDropdownRef">` are separate siblings in the flex row. At `flex-wrap: wrap` widths they can land on different lines, looking disconnected.
  - File: `frontend/src/widgets/chat-shell/ChatView.tsx:229-293`, `chat-view.module.css`
  - Fix: wrap the label and dropdown together in a single `div.collectionGroup` so they always wrap as a unit

- [ ] **7. Magic-number app heights break on mobile browsers** — `workbench-frame.module.css` sets `height: calc(100vh - 48px)` at ≤960px and `calc(100vh - 28px)` at ≤720px. These arbitrary subtractions are unexplained and clip content on browsers with different toolbar heights (e.g., Safari bottom bar).
  - File: `frontend/src/widgets/workbench-frame/workbench-frame.module.css:124,148`
  - Fix: remove the magic subtractions; `.app` already uses `height: 100dvh` on desktop. Mobile should also use `100dvh`.

---

## Visual & Polish Issues

- [ ] **8. Sidebar too narrow (220px) for session titles** — The sidebar `width: 220px` causes most session titles to truncate very early. At 260px there's noticeably more readable title content.
  - File: `frontend/src/widgets/chat-shell/session-sidebar.module.css:25`
  - Fix: change `width: 220px` / `min-width: 220px` to `260px`

- [ ] **9. Pipeline topbar back button is icon-only, chat topbar PDFs button has visible text** — Inconsistent navigation affordance: going to the pipeline you see "PDFs" text; going back you see only a `<` chevron icon.
  - File: `frontend/src/widgets/pipeline-shell/PipelineView.tsx:354-370`
  - Fix: add a visible "Chat" or "← Chat" text label next to the back chevron

- [ ] **10. `offlineBadge` can break topbar layout when shown** — The offline badge is `display: inline` when active (not `inline-flex`), sits inside a `flex-wrap: wrap` container, and can cause unexpected line breaks in the toggle cluster.
  - File: `frontend/src/widgets/chat-shell/chat-view.module.css:186-197`
  - Fix: change `.offlineBadgeShow { display: inline-flex; }` and ensure it wraps with the toggle group

- [ ] **11. Sidebar fade mask clips last visible item** — `mask-image: linear-gradient(to bottom, black 90%, transparent)` always fades the last ~10% of the list even when there's no overflow content.
  - File: `frontend/src/widgets/chat-shell/session-sidebar.module.css:128`
  - Fix: only apply the mask when content overflows, or use a more conservative fade (e.g., `96%` → `transparent`)

---

## Summary

| # | Severity | Area | Status |
|---|----------|------|--------|
| 1 | Critical | ChatComposer CSS mismatch | [ ] |
| 2 | Critical | Code bubble background color | [ ] |
| 3 | High | New Chat shortcut | [ ] |
| 4 | High | Cancel during send | [ ] |
| 5 | High | Drop zone aria-label | [ ] |
| 6 | Medium | Collection label/dropdown grouping | [ ] |
| 7 | Medium | Magic-number mobile heights | [ ] |
| 8 | Medium | Sidebar width | [ ] |
| 9 | Low | Pipeline back button label | [ ] |
| 10 | Low | Offline badge display mode | [ ] |
| 11 | Low | Sidebar fade mask | [ ] |
