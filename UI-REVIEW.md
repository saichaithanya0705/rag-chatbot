# UI Review

**Audited:** 2026-04-02
**Baseline:** Abstract 6-pillar standards
**Screenshots:** Not captured; user requested a code-only audit

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 2/4 | The product voice is generic, and destructive/offline/loading copy is too vague to build confidence. |
| 2. Visuals | 2/4 | The shell lacks a strong information hierarchy; chat, pipeline, and preview surfaces all compete at nearly the same weight. |
| 3. Color | 3/4 | The palette is restrained, but focus states are soft and several components bypass tokens with hardcoded fills/interpolated colors. |
| 4. Typography | 2/4 | Too much of the UI runs on 11-13px text, with almost no true heading structure outside the route fallback. |
| 5. Spacing | 3/4 | Spacing is mostly consistent, but mobile rules solve pressure by hiding context instead of redesigning the layout. |
| 6. Experience Design | 1/4 | Critical states are underdesigned: bootstrap, preview loading, failures, mobile sidebar behavior, and reduced-motion support all have major gaps. |

**Overall: 13/24**

---

## Top 3 Priority Fixes

1. **Fix interaction semantics and hierarchy in the shell** — icon-only controls, fake headings, and missing form labels make the primary workflow harder to scan and less accessible — add real page headings, explicit labels for chat/nav controls, and a proper mobile sidebar/dialog model.
2. **Design real state UX instead of toast-only fallbacks** — bootstrap, session switching, PDF preview loading, and backend failures currently collapse into empty states or transient toasts — use `isBootstrapping`, add inline error/loading surfaces, and show pending states where the user is acting.
3. **Rework the responsive chat/pipeline/PDF layout** — small screens lose essential context because labels are hidden and the PDF panel becomes a cramped bottom sheet — preserve labels, increase type size, and either ship a real viewer or present the PDF surface honestly as a lightweight preview.

---

## Detailed Findings

### Pillar 1: Copywriting (2/4)
- Route fallback copy reads like scaffolding, not product language: `Loading workspace`, `Preparing the chat console`, and `The TypeScript shell is loading the next view.` in `frontend/src/app/router.tsx:11-13` sound internal and disposable.
- The empty states are bland and underspecified. `What would you like to know?` / `Ask questions about your uploaded PDFs` in `frontend/src/widgets/chat-shell/MessageThread.tsx:94-97` and `No PDFs here yet` in `frontend/src/widgets/pipeline-shell/PipelineView.tsx:495-499` do not explain what makes this product useful or what the next best action is.
- Destructive affordances are weak. Both file and session deletion collapse to a tiny `Delete?` chip in `frontend/src/widgets/pipeline-shell/PipelineView.tsx:205-236` and `frontend/src/widgets/chat-shell/SessionSidebar.tsx:114-130`. That copy is ambiguous and easy to misread.
- The offline state is too blunt. `No internet` in `frontend/src/widgets/chat-shell/ChatView.tsx:279-285` says what broke, not what the user can still do.

### Pillar 2: Visuals (2/4)
- The app barely has any real heading structure. The only explicit `h1` in the audited frontend is the route fallback in `frontend/src/app/router.tsx:12`. The actual chat shell and pipeline topbars use spans instead of headings in `frontend/src/widgets/pipeline-shell/PipelineView.tsx:348-364`, and the chat page has no page title at all.
- The pipeline sections are visually organized as accordions, but semantically they are just summaries with uppercase labels. `AccordionSection` renders `SectionLabel as="span"` instead of a heading in `frontend/src/widgets/pipeline-shell/PipelineView.tsx:101-120`, which makes the page feel like a stack of cards rather than a deliberate workflow.
- The PDF viewer is not a viewer. `frontend/src/widgets/pdf-viewer/PdfViewerPanel.tsx:94-123` shows a title, page number, and injected HTML slice. There is no pagination, zoom, search, download, open-in-new-tab, or source context. The label `PDF preview` is generous; the implementation is closer to a static excerpt drawer.
- The knowledge graph has no textual companion and relies on interactive SVG groups as buttons in `frontend/src/widgets/pipeline-shell/KnowledgeGraphView.tsx:183-230`. That is visually clever but operationally brittle and hard to understand at a glance.

### Pillar 3: Color (3/4)
- The palette is fairly disciplined because most surfaces flow through `tokens.css`, but important cues are too soft. The global focus ring is just `rgba(127, 119, 221, 0.35)` in `frontend/src/app/styles/global.css:94-96`, which is easy to lose against the warm background.
- Several pieces bypass the token system. The send icon hardcodes `#EEEDFE` in `frontend/src/widgets/chat-shell/ChatComposer.tsx:60-61`, and the graph computes bespoke fills from `#e8e5d9` and `#d5d0c2` in `frontend/src/widgets/pipeline-shell/KnowledgeGraphView.tsx:206`.
- The graph also leans on very soft line and node colors in `frontend/src/widgets/pipeline-shell/knowledge-graph.module.css:46-57`, which makes the visualization read more like decoration than analysis.

### Pillar 4: Typography (2/4)
- The interface is over-indexed on tiny text. Chat topbar/meta/input affordances sit at 11-13px in `frontend/src/widgets/chat-shell/chat-view.module.css:11,26,109,143,246,291,376`; pipeline metadata does the same in `frontend/src/widgets/pipeline-shell/pipeline-view.module.css:18,63,118,255,262,355,377,385,404,421`; graph labels are 11-12px in `frontend/src/widgets/pipeline-shell/knowledge-graph.module.css:26,92,103,127`.
- Because there are almost no true headings, the serif display font never gets a proper chance to organize the UI. It shows up mostly in empty states and minor labels rather than anchoring the main flow.
- Mobile makes this worse by hiding explanatory text entirely instead of letting typography breathe. `pipelineBtnText`, `collectionLabel`, `inputHint`, and the web toggle text are removed in `frontend/src/widgets/chat-shell/chat-view.module.css:380-425`.

### Pillar 5: Spacing (3/4)
- The overall spacing scale is coherent, but it is used to compress rather than prioritize. The chat topbar, pipeline topbar, and input area all sit in a narrow band of 10-16px padding, which flattens hierarchy across the shell.
- The responsive strategy is blunt. On mobile, the layout hides labels and squeezes controls instead of reorganizing them: `frontend/src/widgets/chat-shell/chat-view.module.css:380-425` and `frontend/src/widgets/pipeline-shell/pipeline-view.module.css:566-590`.
- The PDF panel becomes a fixed 42% bottom sheet on narrow screens in `frontend/src/widgets/pdf-viewer/pdf-viewer.module.css:112-120`, which is a spatial compromise rather than an intentionally designed mobile preview model.

### Pillar 6: Experience Design (1/4)
- `isBootstrapping` is set and cleared in `frontend/src/app/providers/workbench/WorkbenchProvider.tsx:26,67,270,294` but is never consumed anywhere else in the audited frontend. That means the app has no dedicated bootstrap UI; if data fetches are slow or fail, the shell falls through to empty-looking product states instead of an explicit loading/error screen.
- Errors are mostly reduced to toasts or assistant-message replacement text. On bootstrap failure, the provider only sets `toastMessage` in `frontend/src/app/providers/workbench/WorkbenchProvider.tsx:287-298`; the main layout in `frontend/src/widgets/workbench-frame/WorkbenchFrame.tsx:29-37` still renders as if the app is usable.
- Opening a PDF has no pending state. `openPdfPreview` waits for the fetch and only then sets `pdfPreview` in `frontend/src/app/providers/workbench/WorkbenchProvider.tsx:719-725`, so citation clicks can feel dead.
- The mobile sidebar is not a proper modal surface. `frontend/src/widgets/chat-shell/SessionSidebar.tsx:53-65` uses a clickable backdrop div and `aria-hidden`, but there is no `role="dialog"`, no `aria-modal`, no focus trap, and no inerting of the underlying shell.
- The chat composer is underlabelled. The textarea only has a placeholder, and the send button is icon-only with no accessible name in `frontend/src/widgets/chat-shell/ChatComposer.tsx:32-52`.
- The main chat nav controls also rely on `title` instead of robust labels. The history toggle and pipeline button in `frontend/src/widgets/chat-shell/ChatView.tsx:197-203` and `frontend/src/widgets/chat-shell/ChatView.tsx:288-292`, plus the pipeline back button in `frontend/src/widgets/pipeline-shell/PipelineView.tsx:348-360`, are not authored as solid accessible controls.
- Suggestion pills are wired through DOM mutation instead of actual state plumbing. `document.querySelector("textarea")` plus synthetic input dispatch in `frontend/src/widgets/chat-shell/MessageThread.tsx:97-113` is brittle and will age badly the moment another textarea enters the screen.
- Responsive sidebar behavior is driven by `window.innerWidth` snapshots in `frontend/src/app/providers/workbench/WorkbenchProvider.tsx:444-456` and `frontend/src/app/providers/workbench/WorkbenchProvider.tsx:467-478`, which is not a stable interaction model.
- There is no reduced-motion accommodation anywhere in the audited frontend. Multiple components animate (`chat-view.module.css`, `message-thread.module.css`, `pipeline-view.module.css`, `toast.module.css`, `animations.css`), but there is no `prefers-reduced-motion` handling.

---

## Files Audited
- `frontend/src/app/App.tsx`
- `frontend/src/app/router.tsx`
- `frontend/src/app/providers/workbench/WorkbenchProvider.tsx`
- `frontend/src/app/styles/global.css`
- `frontend/src/app/styles/tokens.css`
- `frontend/src/app/styles/animations.css`
- `frontend/src/pages/chat/ChatPage.tsx`
- `frontend/src/pages/pipeline/PipelinePage.tsx`
- `frontend/src/widgets/workbench-frame/WorkbenchFrame.tsx`
- `frontend/src/widgets/chat-shell/ChatView.tsx`
- `frontend/src/widgets/chat-shell/ChatComposer.tsx`
- `frontend/src/widgets/chat-shell/MessageThread.tsx`
- `frontend/src/widgets/chat-shell/chat-view.module.css`
- `frontend/src/widgets/chat-shell/message-thread.module.css`
- `frontend/src/widgets/chat-shell/SessionSidebar.tsx`
- `frontend/src/widgets/chat-shell/session-sidebar.module.css`
- `frontend/src/widgets/pdf-viewer/PdfViewerPanel.tsx`
- `frontend/src/widgets/pdf-viewer/pdf-viewer.module.css`
- `frontend/src/widgets/pipeline-shell/PipelineView.tsx`
- `frontend/src/widgets/pipeline-shell/pipeline-view.module.css`
- `frontend/src/widgets/pipeline-shell/KnowledgeGraphView.tsx`
- `frontend/src/widgets/pipeline-shell/knowledge-graph.module.css`
- `frontend/src/shared/ui/*`
- `frontend/src/shared/api/httpWorkbench.ts`
- `frontend/src/shared/api/types.ts`
- `frontend/src/shared/lib/messageHtml.ts`
