# Local RAG Chatbot — Phased Build Plan

Reference: `rag_chatbot_plan.md` for full technical details.
Reference: `chatbot_ui_mockup.html` for UI reference.

---

## Guiding principle

Each phase produces a **working, usable system** — not a half-built one.
Phase 1 alone is a functional chatbot. Each subsequent phase upgrades it without breaking what's already there.

---

## Phase 1 — Bare minimum working RAG chat

**Goal:** Upload a PDF, ask a question, get an answer with a citation. Nothing else.

### Backend
- FastAPI project scaffold (`main.py`, `routers/`, `services/`)
- Ollama integration — confirm all-minilm embeddings and 4B LLM are callable
- **Ingestion (simplified):**
  - PyMuPDF parse with header/footer strip (Stage 1)
  - Recursive character splitting as placeholder — semantic chunking comes in Phase 2
  - Embed chunks with all-minilm 384-dimensional vectors → store in a **single flat ChromaDB collection** (no topics yet)
  - Attach metadata: `{pdf_name, page_number, chunk_index}`
- **Query (simplified):**
  - Embed query → vector search only (no BM25, no KG, no reranker)
  - Top-5 chunks → pack into prompt with `[Source: PDF, p.N]` labels
  - Call Ollama 4B → return full response (no streaming yet)
  - Parse `[Source:]` markers → return citations alongside answer

### Frontend
- Plain React scaffold
- Single page: textarea input + response display
- Show citations as static text chips below response
- No sidebar, no PDF panel, no pipeline page

### Storage
- ChromaDB: one flat collection `all_chunks`
- SQLite: `sessions` + `messages` tables created but not actively used yet
- No KG yet

### Done when
You can upload a PDF via a script (not UI), ask a question via the frontend, and get a cited answer back.

---

## Phase 2 — Streaming + History + Proper Ingestion

**Goal:** Chat feels live. History persists. Ingestion is production-quality.

### Backend
- **Streaming:** swap full response for FastAPI `StreamingResponse` + Ollama stream
- **History Manager (core):**
  - `save_turn()` after each completed stream
  - `load_session()` for sidebar
  - `list_sessions()` for sidebar
  - Sliding window: inject last 3 turns into prompt
  - Session auto-title: LLM title generation as background task after first message
- **Ingestion upgrade:**
  - Replace recursive splitting with **semantic chunking** (all-minilm, threshold=0.75)
  - Add **KeyBERT** keyword extraction (top 5 per chunk)
  - Store keywords in chunk metadata

### Frontend
- **Collapsible sidebar** — session list grouped by date, active highlight, new chat button
- **Streaming render** — tokens appear as they arrive
- **Citation chips** — clickable, open PDF viewer panel (static placeholder for now)
- **Collection dropdown** in topbar (static for now — just "All PDFs")

### Storage
- SQLite fully active: sessions + messages + citations JSON
- ChromaDB still flat `all_chunks` (topics come in Phase 3)

### Done when
Conversations persist, reload correctly from sidebar, responses stream live, and ingestion produces clean semantic chunks with keywords.

---

## Phase 3 — Topic Clustering + KG + Hybrid Retrieval

**Goal:** Retrieval becomes topic-aware. KG is built and used for expansion.

### Backend
- **HDBSCAN clustering** after ingestion:
  - Pull staging embeddings → cluster → assign topic labels
  - Move chunks into per-topic ChromaDB collections (`slugify(topic_label)`)
  - Merge overlapping clusters (centroid similarity > 0.85)
- **KG construction** (`kg_manager.py`):
  - Nodes = topic clusters with centroids, chunk_ids, pdf_sources, keyword_summary
  - Edges = two-signal weight (α=0.6 centroid sim + β=0.4 co-occurrence), prune < 0.4
  - In-memory singleton + pickle persistence
  - Hot-swap on re-cluster
- **Query Handler upgrade:**
  - Topic routing: score query vs centroids → top-3 topics
  - KG expansion: 1-hop neighbors, edge > 0.4, cap 6 collections
  - BM25 retrieval (rank_bm25) per collection alongside vector search
  - RRF merge (k=60)
  - Cross-encoder reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2`, top-7 chunks
- **Re-cluster trigger:** on every upload + manual API endpoint

### Frontend
- **Collection dropdown** now populated from real topic labels
- **Pipeline page (Phase 3 version):**
  - Topic pills (auto-detected, clickable)
  - File list with topic chips + chunk count per PDF
  - Re-cluster button wired to backend
  - Progress bar: Parsing → Chunking → Embedding → Clustering
- **Toast notification** on indexing complete

### Storage
- ChromaDB: per-topic collections + staging collection
- NetworkX KG: `kg.pkl` on disk, in-memory singleton
- SQLite: `topic_overrides` table created (empty for now)

### Done when
Asking about "Round Robin" also retrieves relevant chunks from "process synchronization" and "deadlock" collections via KG expansion. Retrieval quality is noticeably better than Phase 2.

---

## Phase 4 — Chat RAG + PDF Viewer + Full Pipeline UI

**Goal:** Long conversations stay coherent. Citations are clickable and show real content. Pipeline UI is complete.

### Backend
- **History Manager upgrade — Chat RAG:**
  - Embed each completed turn → store in flat `chat_history` ChromaDB collection
    with `{session_id, user_id: "default", created_at}` metadata
  - `get_hybrid_memory()`: sliding window (last 3) + chat RAG (top-3, filtered by session_id)
  - Deduplication + ordering (relevant first, recent last)
  - Session delete: clean both SQLite and ChromaDB
- **KG visualizer API endpoint:** `GET /api/kg/graph` → returns nodes + edges as JSON

### Frontend
- **PDF viewer panel** — slide-in from right, rendered PDF text with highlighted passage
  - Citation chip click → open panel at correct page
  - Close button
- **Pipeline UI (complete):**
  - Topic overlap badge per PDF ("3 shared topics with DBMS_Notes.pdf")
  - KG visualizer: force-directed graph (D3), node size = chunk count, edge thickness = weight
  - Clicking a KG node scopes collection dropdown in chat
- **Session delete** in sidebar (right-click or hover ×)

### Storage
- ChromaDB `chat_history` collection active
- SQLite: `topic_overrides` table in use

### Done when
You can have a 30-turn conversation where the bot still recalls relevant answers from turn 3 when asked a follow-up at turn 28. PDF panel opens at the right page with the right highlight. KG is visible on the Pipeline page.

---

## Phase 5 — Web Search + Polish

**Goal:** When PDFs don't have the answer, web search fills the gap gracefully.

### Backend
- DuckDuckGo/Brave search integration
- Auto-fallback logic: top rerank score < 0.3 → trigger web search (if toggle ON)
- Format web results as context with `[Web: url]` citations
- Offline detection: catch connection error → return "No internet" warning

### Frontend
- **Web search toggle** fully wired (on/off, offline badge)
- **Collapsible tool-call block** above answer when web search fires
  (shows: "Searched the web for: {query}")
- **"Web search used" badge** at bottom of message
- Minor polish: loading states, error toasts, empty states

### Done when
Asking a question outside your PDFs (e.g. "what is the latest Linux kernel version?") triggers web search automatically, shows the thinking block, and cites the web source. Turning off the toggle falls back to PDF-only gracefully.

---

## Phase 6 — V2 Backlog Items (completed in Phases 1–5)

These were planned for Phase 6 but were **implemented during Phases 1–5**:

| Feature | Where it landed | Status |
|---|---|---|
| Cross-session chat RAG | Phase 4 (`HistoryService`) | ✅ `cross_session_memory_enabled=True` default |
| LLM query rewriting | Phase 2 (`query_rewrite_service.py`) | ✅ Full rewrite with history context |
| LLM-based topic tagging | Phase 2 (`keyword_service.py`) | ✅ LLM primary + KeyBERT fallback |
| Celery worker | Phase 3 (`ingestion_dispatcher.py`) | ✅ Filesystem broker |
| OCR support | Phase 3 (`ocr_service.py`) | ✅ Surya backend |
| Cross-user memory | Phase 4 (infra ready) | ⚠️ `user_id` in DB + `x-user-id` header, no auth |

---

## Phase 7 — V2 Full-Stack Enhancements

**Goal:** Elevate from functional prototype to polished product. Frontend component adoption, file management UX,
knowledge graph interactivity, and backend intelligence improvements.

> Vintage palette unchanged. All changes work within existing warm parchment color tokens.

### Frontend — F1: Shared Component Adoption
- Wire 5 built-but-unused components: `Toast`, `CitationChip`, `SectionLabel`, `StatusPill`, `SurfaceCard`
- Replace inline markup in `WorkbenchFrame`, `MessageThread`, `PipelineView`
- Remove duplicated CSS (`.toast`, `.toastShow` from `workbench-frame.module.css`)

### Frontend — F2: File Cards Redesign + List/Card Toggle
- Add `viewMode: "list" | "card"` state toggle (default: **list**)
- **Card mode**: vertical layout — icon/name/status header, metadata middle, topic chips footer
- CSS grid: `repeat(auto-fill, minmax(280px, 1fr))`
- Inline delete confirmation: first click → "Delete? / Cancel", 3-second auto-dismiss

### Frontend — F3: Collapsible Accordion Sections
- Wrap Upload, Files, Knowledge Graph in `<details open>` with `<SectionLabel>` summary
- Animated chevron rotation, `fadeSlideIn` entrance on content
- Collections section stays always visible

### Frontend — F4: Knowledge Graph Enhancements
- Color-coded nodes: fill interpolation by chunk count (`#e8e5d9` → `#d5d0c2`)
- SVG `<foreignObject>` tooltip: topic label + doc count + chunk count on hover
- Empty state: dashed-circle SVG with 3 connected dots

### Frontend — F5: Chat Empty State Illustration
- Inline SVG: stacked papers with sparkle accent
- Uses `var(--border-strong)` lines and `var(--accent)` sparkle

### Frontend — F6: Sidebar Auto-Close on Pipeline
- `useEffect` closes sidebar when view switches to Pipeline

### Frontend — F7: Advanced Keyboard Interactions
- Dropdown: `ArrowDown`/`ArrowUp` cycle, `Enter` select, `Home`/`End` jump
- Session sidebar: `Delete`/`Backspace` key triggers deletion with visual flash

### Frontend — F8: Contrast Audit & Cleanup
- Replace all `var(--text-subtle)` / `#888780` with `var(--text-subtle-aa)` for WCAG AA
- Deprecation comment on `--text-subtle` token

---

### Backend — B1: Cross-Session Memory Hardening
Current state: implemented but lacks guardrails and observability.
- Add minimum distance threshold to `_query_memory_turns()` — skip turns with distance > 1.2
- Return `cross_session_count` from `get_hybrid_memory()` — count of turns from other sessions
- Add `crossSessionMemoryUsed: int` to `ChatResponse` and stream `done` payload
- Frontend badge: "📎 Used context from N other sessions" below assistant messages

### Backend — B2: SSE Ingestion Progress Stream
- `GET /api/events/ingestion-progress` — SSE endpoint
- **SQLite polling** every 2 seconds (no Redis dependency)
- Heartbeat ping every 15s, auto-close after 30s idle
- Frontend: `EventSource` subscriber updates `state.pipelineDocuments` in real-time

### Backend — B3: Document Analytics & Session Export
- `GET /api/analytics/summary` — total docs, chunks, topics, avg chunks/doc, storage bytes
- `GET /api/sessions/{id}/export` — downloadable JSON with all messages + citations
- `Content-Disposition: attachment` response header

### Backend — B4: Adaptive Chunking Threshold
- `auto_tune_threshold(page_texts)` — samples up to 5 pages, computes mean sentence similarity
- Threshold range: 0.68 (diverse docs) – 0.82 (homogeneous docs)
- Called once per document at ingestion start, logged for observability

---

## Dependency Map

```
Phase 1  →  Phase 2  →  Phase 3  →  Phase 4  →  Phase 5  →  Phase 6 (✅)  →  Phase 7
  │              │            │            │            │                          │
  │         streaming      KG + topics   chat RAG    web search              V2 full-stack
  │         history        hybrid retr.  PDF viewer   polish                    │
  │         semantic       reranker      KG viz                     ┌───────────┼───────────┐
  └─ basic RAG             pipeline UI                          Frontend    Backend      Backend
     (vector only)                                              F1–F8       B1–B2       B3–B4
                                                                 (UI)      (infra)    (analytics)
```

Each phase strictly builds on the previous. Phase 7 sub-phases (F1–F8, B1–B4)
can be executed in parallel across frontend and backend tracks.

---

## Estimated Complexity Per Phase

| Phase | Core challenge | Relative effort |
|---|---|---|
| 1 | Getting Ollama + ChromaDB + FastAPI talking | Low |
| 2 | Streaming + SQLite session management | Low-Medium |
| 3 | HDBSCAN stability + KG construction + BM25 index management | High |
| 4 | Chat RAG deduplication logic + D3 visualizer | Medium |
| 5 | Offline detection + streaming with web source mixing | Low-Medium |
| 6 | (Already completed during Phases 1–5) | — |
| 7-F1 | Component wiring + CSS cleanup | Low |
| 7-F2 | List/card toggle + delete confirmation | Medium |
| 7-F3 | Accordion animation | Low |
| 7-F4 | SVG foreignObject tooltip + chart color coding | Medium |
| 7-F5 | Inline SVG illustration | Low |
| 7-F6 | Sidebar effect | Low |
| 7-F7 | Keyboard state management | Medium |
| 7-F8 | CSS audit pass | Low |
| 7-B1 | Cross-session memory audit + schema extension | Medium |
| 7-B2 | SSE endpoint + SQLite polling loop | Medium |
| 7-B3 | Analytics aggregation + export serialization | Low-Medium |
| 7-B4 | Auto-tune algorithm + ingestion integration | Medium |

Phase 3 is the hardest. HDBSCAN can produce noisy clusters on small datasets — plan to
spend time tuning `min_cluster_size` and `min_samples` parameters. Start with
`min_cluster_size=3, min_samples=2` and adjust based on how many PDFs you have indexed.
