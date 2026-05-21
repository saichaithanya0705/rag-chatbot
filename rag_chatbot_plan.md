# Local RAG Chatbot — Master Plan

## Project Overview
A fully offline-first, local RAG-based chatbot for learning purposes.
Upload PDFs → auto-index into topic-based vector store → chat with your notes.
Optional web search (auto-fallback when PDFs don't have the answer).

**Core stack:** FastAPI · React · Ollama (4B LLM + all-minilm 384-dimensional embeddings) · ChromaDB · SQLite · NetworkX

---

## Architecture

### Tiers
| Tier | Components |
|---|---|
| Frontend | Chat UI · PDF viewer panel · Pipeline UI · KG visualizer · Web search toggle |
| Backend | Query handler · Ingestion handler · History manager · KG manager |
| AI | Ollama (4B LLM + all-minilm 384-dimensional embeddings) · Cross-encoder reranker · Web search (DuckDuckGo/Brave) |
| Storage | ChromaDB (per-topic collections + flat chat_history collection) · NetworkX KG (in-memory + pickle) · SQLite (sessions + messages + ingestion status + topic overrides) |

### Two pipelines
- **Ingestion pipeline** — background task; PDF → parse → chunk → embed → cluster → KG rebuild → store
- **Query pipeline** — real-time; query → embed → KG topic route → hybrid retrieve → rerank → history inject → LLM → stream

---

## UI Plan

### Artifact
**File:** `chatbot_ui_mockup.html`
Interactive mockup of the full UI. Open in any browser — all interactions wired.

### Chat UI (main view)
- **Left sidebar** — collapsible via hamburger toggle in topbar
  - Sessions grouped by date: Today / Yesterday / Last 7 days
  - Auto-generated session title (LLM, ~5 words, fire-and-forget after first message)
  - Active session highlighted with purple left border
  - "New chat" button at top
- **Topbar**
  - Hamburger (☰) → collapse/expand sidebar
  - Collection dropdown → scope retrieval to a topic group
  - Web search toggle (on/off) → "No internet" badge when offline
  - Grid icon (⊞) → navigate to Pipeline page
- **Message thread**
  - User bubbles: right-aligned, purple
  - Bot bubbles: left-aligned, gray surface
  - Citation chips below each bot message → `PDF_name.pdf · p.N`
  - Clicking a chip opens PDF viewer panel at that page with highlighted passage
  - **Web search indicator** (when auto-fallback triggers):
    - Collapsible "tool call" block above answer showing search query used
    - Small "Web search used" badge at bottom of message
- **PDF viewer panel** — right side, slide-in, highlighted passage, close with ×
- **Input bar** — textarea + send, Enter to send, Shift+Enter for newline
- **Memory strategy** — hybrid: sliding window (last 3 turns) + chat RAG (top-3 relevant past turns)

### Pipeline UI (separate page — Option A)
- Accessed via ⊞ in topbar, replaces chat view fully. Back arrow returns to chat.
- **Collections row** — auto-detected topic pills (content-based). "+ New" for manual.
- **Drop zone** — click or drag to upload PDFs
- **Per-PDF file row:**
  - File name, size, page count, date added
  - **Topic chips** — auto-detected (clicking shows all PDFs sharing that topic)
  - **Chunk count** — e.g. "38 chunks"
  - **Topic overlap badge** — e.g. "3 shared topics with DBMS_Notes.pdf"
  - **Progress bar** — Parsing → Chunking → Embedding → Clustering (color-coded)
  - Status: Queued / Chunking / Embedding / Indexed / Error · Delete (×)
- **Re-cluster topics button** — manually trigger re-clustering on demand
- **KG visualizer** — force-directed graph (D3 or vis.js) on Pipeline page
  - Nodes = topic labels, sized by chunk count
  - Edge thickness = edge weight
  - Clicking a node scopes chat collection to that topic
- **Toast** — fires on indexing complete, visible from chat view too

---

## Ingestion Handler Plan

### Stage 1 — PDF Parsing & Header/Footer Stripping

**Library:** `PyMuPDF` (`fitz`). All PDFs are browser-printed → text-based, no OCR needed.
Stripping done during parsing. Browser-printed PDFs: headers in top ~8%, footers in bottom ~8%.

```python
def extract_page_text(page):
    blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, ...)
    page_h = page.rect.height
    clean = [
        b[4] for b in blocks
        if b[1] > page_h * 0.08
        and b[3] < page_h * 0.92
        and b[4].strip()
    ]
    return "\n".join(clean)
```

**Output:** clean text per page + `{pdf_name, page_number}`

---

### Stage 2 — Semantic Chunking

Split where cosine similarity between adjacent sentences drops below threshold.

```python
def semantic_chunk(sentences, threshold=0.75):
    embeddings = [ollama.embed("all-minilm", s) for s in sentences]
    chunks, current = [], [sentences[0]]
    for i in range(1, len(sentences)):
        sim = cosine_similarity(embeddings[i-1], embeddings[i])
        if sim < threshold:
            chunks.append(" ".join(current))
            current = []
        current.append(sentences[i])
    if current:
        chunks.append(" ".join(current))
    return chunks
```

**Threshold:** 0.75 default. **Output:** chunk text + `{pdf_name, page_number, chunk_index}`

---

### Stage 3 — Keyword Extraction

**v1:** KeyBERT with all-minilm embedding backbone. Top **5 keyphrases** per chunk.
Stored as `{..., "keywords": ["scheduling", "round robin", ...]}` in chunk metadata.

**v2 (planned):** LLM-based tagging via 4B model prompt:
> *"List 2-3 topic tags for this text. Reply only with comma-separated tags."*

---

### Stage 4 — Embedding & Staging

Embed each chunk (all-minilm, 384 dimensions). Store in flat ChromaDB **staging collection** with full metadata.
Topic labels assigned after clustering in Stage 5.

---

### Stage 5 — Clustering & Topic Assignment

**Algorithm:** HDBSCAN. Triggered on every upload + manually via UI.

1. Pull all embeddings from staging
2. HDBSCAN → cluster label per chunk
3. Majority-vote KeyBERT keywords → topic label
4. Merge overlapping topics (centroid similarity > 0.85)
5. Move chunks into per-topic ChromaDB collections: `collection_name = slugify(topic_label)`

**Final chunk metadata:** `{pdf_name, page_number, chunk_index, topic, keywords[], collection_id}`

---

### Stage 6 — Knowledge Graph Construction

See **Knowledge Graph Plan** section below for full details.
Called after every Stage 5 re-cluster. Rebuilds KG fully from new topic assignments.

---

### Stage 7 — SQLite Update & UI Event

Update `pdfs` table: `status="indexed"`, `topics[]`, `chunk_count`, `indexed_at`
Emit event → UI: Indexed status + topic chips + chunk count + toast

---

### Full Ingestion Flow

```
PDF upload
  → Stage 1: PyMuPDF parse + strip headers/footers (y-coord, top/bottom 8%)
  → Stage 2: Sentence tokenize → semantic chunk (all-minilm, threshold=0.75)
  → Stage 3: KeyBERT keyword extraction (top 5 per chunk)
  → Stage 4: Embed chunks → store in ChromaDB staging collection
  → Stage 5: HDBSCAN re-cluster → topic labels → per-topic ChromaDB collections
  → Stage 6: Rebuild KG (see KG Plan)
  → Stage 7: SQLite update → emit UI event
```

---

## Query Handler Plan

### Stage 1 — Query Preprocessing
Lowercase + strip for v1.
**v2:** LLM query rewriting before embedding.

---

### Stage 2 — Topic Routing via KG

1. Embed query (all-minilm, 384 dimensions) → query vector
2. Score against all topic centroid embeddings → **top-3 topics**
3. KG expand: 1-hop neighbors, edge weight > 0.4, capped at **6 collections max**

See KG Plan — Query Time section for expansion logic.

---

### Stage 3 — Hybrid Retrieval

Per expanded collection: vector search (ChromaDB, top-10) + BM25 (rank_bm25, top-10).
Merge with RRF (k=60). Output: ~30-50 candidate chunks.

```python
def reciprocal_rank_fusion(vector_results, bm25_results, k=60):
    scores = {}
    for rank, chunk_id in enumerate(vector_results):
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (rank + k)
    for rank, chunk_id in enumerate(bm25_results):
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (rank + k)
    return sorted(scores, key=scores.get, reverse=True)
```

---

### Stage 4 — Cross-Encoder Reranking

**Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2` (~80MB, CPU-friendly). Select **top-7**.
Top rerank score saved for Stage 6 web search decision.

---

### Stage 5 — Context Packing

- Order top-7 by page number within same PDF
- Inject `[Source: PDF_name, p.N]` labels
- Token budget: ~1K system+history / ~2K chunks / ~1K answer
- Truncate from bottom if over budget

---

### Stage 6 — Web Search Fallback

**Triggers:** toggle ON **and** top rerank score < 0.3.
Format results as `[Web: url]`. UI: collapsible tool-call block + "Web search used" badge.
If offline: warn user, fall back to best PDF chunks.
If toggle OFF: never auto-fallback.

---

### Stage 7 — History Injection

Call History Manager → hybrid memory (last 3 turns + top-3 chat RAG turns, deduplicated).

**Prompt structure:**
```
[System prompt]
[Retrieved context with [Source:] labels]
[Relevant past turns — chat RAG]
[Recent turns — sliding window]
[Current query]
```

---

### Stage 8 — LLM Call & Streaming

Stream via `StreamingResponse`. On completion: parse citations → save to SQLite →
embed turn → store in `chat_history` ChromaDB collection.

---

### Full Query Flow

```
User query
  → Stage 1: Clean query
  → Stage 2: Embed → top-3 KG topic match → expand (1-hop, cap 6 collections)
  → Stage 3: Hybrid retrieval (vector + BM25 → RRF) → ~30-50 chunks
  → Stage 4: Cross-encoder rerank → top-7 chunks
  → Stage 5: Context pack (page order, [Source:] labels, token budget)
  → Stage 6: Web search check (toggle ON + score < 0.3 → fallback + UI indicators)
  → Stage 7: History Manager → hybrid memory → build full prompt
  → Stage 8: Ollama stream → parse citations → save SQLite → embed turn → ChromaDB
```

---

## History Manager Plan

### SQLite Schema

```sql
CREATE TABLE sessions (
    id           TEXT PRIMARY KEY,
    title        TEXT,
    collection   TEXT,
    created_at   DATETIME,
    updated_at   DATETIME
);

CREATE TABLE messages (
    id           TEXT PRIMARY KEY,
    session_id   TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    role         TEXT,               -- 'user' | 'assistant'
    content      TEXT,
    citations    TEXT,               -- JSON: [{pdf_name, page, chunk_id}]
    embedding_id TEXT,               -- ChromaDB doc id for this turn
    created_at   DATETIME
);

CREATE TABLE topic_overrides (
    cluster_id   TEXT PRIMARY KEY,   -- stable cluster id from HDBSCAN
    display_name TEXT,               -- user-edited topic name
    updated_at   DATETIME
);
```

---

### ChromaDB — chat_history collection

**One flat collection:** `chat_history`. Metadata per turn: `{session_id, user_id, created_at}`.

**v1:** Always filter by `session_id` → scoped to current session.
**v2 (cross-session RAG):** Remove `session_id` filter. No schema change needed — metadata already there.

```python
# v1 — scoped query
collection.query(
    query_embeddings=[query_vector],
    n_results=3,
    where={"session_id": session_id}   # ← remove this line for v2
)
```

---

### Session Management

**Create:** INSERT session row. Title = "New chat" initially.

**Auto-title (LLM, fire-and-forget after first message):**
```python
async def generate_title(session_id, first_message):
    prompt = f"Summarize this in 5 words or less as a chat title: '{first_message}'"
    title = await ollama.generate("4b-model", prompt)
    db.execute("UPDATE sessions SET title=? WHERE id=?", (title.strip(), session_id))
```

**Load:** SELECT all messages for session, parse citations JSON → frontend re-renders chips.
**Delete:** DELETE session (CASCADE removes messages) + delete from chat_history ChromaDB.

---

### Message Persistence

Called after streaming completes (never mid-stream):
- INSERT user message row
- INSERT bot message row + citations JSON
- UPDATE sessions.updated_at
- Embed full turn → store in chat_history ChromaDB

---

### Hybrid Memory Retrieval

```python
def get_hybrid_memory(session_id, query_vector, n_recent=3, n_relevant=3):
    recent   = get_last_n_turns(session_id, n=n_recent)          # SQLite
    relevant = chat_rag_search(session_id, query_vector, n=n_relevant)  # ChromaDB
    recent_ids = {t["id"] for t in recent}
    relevant   = [t for t in relevant if t["id"] not in recent_ids]
    return relevant + recent   # relevant first, recent last
```

**Ordering:** relevant (older, deep context) first → recent (conversational flow) last → current query.
LLM attends most strongly to content immediately before the query, so recent turns go closest.

---

## Knowledge Graph Plan

### What the KG Is

A **topic relationship map** derived entirely from your PDFs. Nothing hardcoded.
Nodes = topics that emerged from HDBSCAN clustering. Edges = learned relationships from
your study material (semantic similarity + co-occurrence on same pages).

---

### Node Structure

Each node stores:
```python
{
  "label":           "cpu_scheduling",          # slugified, stable id
  "display_name":    "CPU Scheduling",          # shown in UI (overrideable)
  "centroid":        [...],                     # mean embedding of all chunks in topic
  "chunk_ids":       [...],                     # all ChromaDB chunk ids in this topic
  "pdf_sources":     ["OS_Notes_Unit3.pdf"],    # which PDFs contribute
  "keyword_summary": ["scheduling", "round robin", "FCFS", "preemption"]
}
```

---

### Edge Weight — Two-Signal Formula

Pure centroid cosine similarity is insufficient — topics sharing common vocabulary
(e.g. both use "process") get falsely close edges. Two signals are combined:

**Signal 1 — Centroid cosine similarity** (semantic closeness, α=0.6)
**Signal 2 — Chunk co-occurrence** (how often both topics appear on the same PDF pages, β=0.4)

```python
def compute_edge_weight(topic_a, topic_b, alpha=0.6, beta=0.4):
    # signal 1: semantic
    sem_sim = cosine_similarity(topic_a["centroid"], topic_b["centroid"])

    # signal 2: co-occurrence
    pages_a = set((c["pdf_name"], c["page_number"]) for c in topic_a["chunks"])
    pages_b = set((c["pdf_name"], c["page_number"]) for c in topic_b["chunks"])
    shared   = len(pages_a & pages_b)
    total    = len(pages_a | pages_b)
    co_occur = shared / total if total > 0 else 0

    return alpha * sem_sim + beta * co_occur
```

**Prune** edges with weight < 0.4. Graph is **undirected** (retrieval is symmetric).

---

### KG Manager — In-Memory Singleton + Disk Persistence

KG lives in memory as a module-level singleton. Loaded from disk on FastAPI startup.
Rebuilt and hot-swapped after every re-cluster — no app restart needed.

```python
# kg_manager.py
import networkx as nx, pickle

_kg: nx.Graph = None

def get_kg() -> nx.Graph:
    global _kg
    if _kg is None:
        _kg = load_kg_from_disk()
    return _kg

def rebuild_kg(topics: list[dict]) -> nx.Graph:
    G = nx.Graph()
    for t in topics:
        G.add_node(t["label"], **t)
    for i, ta in enumerate(topics):
        for tb in topics[i+1:]:
            w = compute_edge_weight(ta, tb)
            if w >= 0.4:
                G.add_edge(ta["label"], tb["label"], weight=w)
    save_kg_to_disk(G)
    global _kg
    _kg = G
    return G

def save_kg_to_disk(G):
    with open("kg.pkl", "wb") as f:
        pickle.dump(G, f)

def load_kg_from_disk() -> nx.Graph:
    with open("kg.pkl", "rb") as f:
        return pickle.load(f)
```

---

### Query Time — Topic Routing + Expansion

**Step 1:** Score query vector against all node centroids → top-3 topics.

**Step 2 — Bounded 1-hop expansion:**
Expansion can blow up for highly connected nodes (e.g. "processes" in an OS course).
Cap at **6 collections max**. Take strongest neighbors first by edge weight:

```python
def expand_topics(matched, kg, edge_threshold=0.4, max_collections=6):
    expanded = set(matched)
    candidates = []
    for topic in matched:
        for neighbor, attrs in kg[topic].items():
            if attrs["weight"] > edge_threshold and neighbor not in expanded:
                candidates.append((attrs["weight"], neighbor))
    candidates.sort(reverse=True)
    for _, neighbor in candidates:
        if len(expanded) >= max_collections:
            break
        expanded.add(neighbor)
    return list(expanded)
```

---

### Update Time — Re-cluster Effects

Re-clustering can **split**, **merge**, or **rename** topic nodes. The KG is always rebuilt
fully from scratch after re-cluster — no incremental patching (graph is small, fast to rebuild).

**User-facing topic names survive re-clustering** via `topic_overrides` table in SQLite:
- After every rebuild, re-apply overrides: if `cluster_id` matches, set `display_name` from override
- If a cluster is split or merged, the old `cluster_id` disappears — override is orphaned (ignored silently)
- User can re-rename in the UI if needed

---

### KG Visualizer (Pipeline UI)

Force-directed graph (D3 force layout or vis.js) on the Pipeline page:
- **Node size** = chunk count (bigger topic = bigger node)
- **Edge thickness** = edge weight
- **Node color** = PDF source (if topic spans multiple PDFs, blended or striped)
- **Clicking a node** → scopes the chat collection dropdown to that topic
- Rendered from a `/api/kg/graph` endpoint that returns nodes + edges as JSON

---

## V2 Backlog — Status

### ✅ Implemented (Phases 1–5 completed)
| Feature | Implementation |
|---|---|
| Cross-session chat RAG | `cross_session_memory_enabled=True` default; `HistoryService` filters by `user_id` not `session_id` |
| LLM query rewriting | `query_rewrite_service.py` — full LLM rewrite with conversation history context |
| LLM-based topic tagging | `keyword_service.py` — `_extract_keywords_with_llm()` with KeyBERT fallback |
| Celery worker | `ingestion_dispatcher.py` + `celery_app.py` — filesystem broker |
| OCR support | `ocr_service.py` — surya_ocr backend, enabled by default |
| Cross-user memory | `user_id` in all DB queries + `x-user-id` header from frontend (UUID in localStorage) |

### 🔧 V2 Frontend Enhancements (Phase 7)
| Feature | Details |
|---|---|
| Shared component adoption | Wire `Toast`, `CitationChip`, `SectionLabel`, `StatusPill`, `SurfaceCard` into app |
| File card list/card toggle | Toggle between horizontal list (default) and vertical card grid layout |
| Collapsible pipeline sections | `<details>` accordions for Upload, Files, Knowledge Graph |
| KG SVG tooltips | Color-coded nodes by chunk count, `<foreignObject>` tooltip on hover, empty state SVG |
| Chat empty state illustration | Inline SVG with stacked papers + sparkle accent |
| Sidebar auto-close on Pipeline | `useEffect` triggers close when switching to Pipeline view |
| Advanced keyboard nav | Dropdown arrow keys, Delete key for sessions, Home/End jump |
| WCAG contrast audit | Replace `--text-subtle` with `--text-subtle-aa` system-wide |

### 🔧 V2 Backend Enhancements (Phase 7)
| Feature | Details |
|---|---|
| Cross-session memory hardening | Add relevance threshold (distance > 1.2 → skip), `crossSessionMemoryUsed` count in response, UI badge |
| SSE ingestion progress | `GET /api/events/ingestion-progress` SSE endpoint, SQLite polling every 2s, replaces frontend polling |
| Document analytics API | `GET /api/analytics/summary` — total docs/chunks/topics, avg chunks/doc, storage used |
| Session export | `GET /api/sessions/{id}/export` — downloadable JSON with all messages + citations |
| Adaptive chunking threshold | `auto_tune_threshold()` — per-document threshold 0.68–0.82 based on sentence similarity distribution |

### ❌ Deferred (V3+)
| Feature | Notes |
|---|---|
| Directed KG edges | Prerequisite chain modeling (`nx.DiGraph`), needs manual curation UI |
| Authentication | Real auth system beyond `x-user-id` header |

---

## Phased Build Plan
*(see rag_chatbot_phases.md)*
