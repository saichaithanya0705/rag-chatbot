# AI-Slop Audit — OpenDataLoader Migration

**Scope:** The Docling-to-OpenDataLoader migration, its parser-to-knowledge-graph spine,
embedding runtime selection, Chroma publication, and Docker/Render readiness contract.
Graphify report reviewed: `graphify-out/GRAPH_REPORT.md` (2026-08-29; 1,459 nodes,
2,666 relationships). The Graphify scanner was used as triage only; its pattern-only
score is not this verdict.

## Verdict

**Score: 24/100 — Low slop risk**
**Confidence: High**

The migration surface is now contract-driven and covered by parser, ingestion, vector
publication, knowledge-graph, embedding, and deployment-readiness tests. The remaining
risk is governance: this repository has no checked-in CI workflow to make those checks
mandatory before a deploy.

## Why

- Graphify identifies the parser, chunk catalog, embedding storage, and knowledge-graph
  flow as connected high-blast-radius communities; source tests now prove their hand-offs.
- The migration removed active Docling references outside this historical audit and replaced
  the old parser with a single OpenDataLoader/PDFium boundary.
- Confirmed data-integrity defects were repaired at their owning contracts, not hidden with
  fallback behavior.
- Scanner hits for prompts, retries, `subprocess.Popen`, and optional-parser fallback were
  reviewed. They are legitimate, bounded behaviors rather than evidence of unsafe agent tools
  or dead indirection.

## Evidence

| Signal | Graph evidence | Source evidence | Classification | Root cause | Permanent fix | Prevention gate |
|---|---|---|---|---|---|---|
| Local fallback could use 384-dimensional embeddings while index metadata declared a configured 1024 dimensions | Embedding index storage and compatibility safety are connected graph communities | `backend/app/services/nvidia_client.py`, `backend/app/services/container.py`, `backend/tests/test_nvidia_client.py` | Confirmed slop signal — fixed | Model resolution and index reconciliation resolved different pieces of the runtime contract | `EmbeddingRuntime` resolves model, dimensions, and cloud/local mode once; both Chroma reconciliation and the client use it | Test cloud-model configuration with and without an API key |
| Cloud embedding response parsing trusted malformed payloads and retried all exceptions | `NvidiaClient` bridges answer generation and embedding storage | `backend/app/services/nvidia_client.py`, `backend/tests/test_nvidia_client.py` | Confirmed slop signal — fixed | External JSON was treated as a happy-path dictionary | Validates cardinality, list shape, and numeric vectors; only transport failures retry | Contract test malformed and short responses |
| SSE parser silently discarded all malformed events | `NvidiaClient` is in the chat delivery path | `backend/app/services/nvidia_client.py`, `backend/tests/test_nvidia_client.py` | Confirmed slop signal — fixed | Broad exception suppression hid provider protocol drift | Catches only expected parsing failures and logs a warning while preserving later valid deltas | Stream fixture with malformed then valid event |
| OpenDataLoader optional-engine fallback uses broad exceptions | PDF ingestion parsing is a cohesive, high-use community | `backend/app/services/opendataloader_parser.py`, `backend/tests/test_opendataloader_parser.py` | Benign, governed boundary | Two independent external PDF engines can fail on document-specific input | Errors are retained and surfaced in the final user-facing failure; tests cover digital, blank-page, nested-structure, margin, and no-text cases | Keep both-engine failure and provenance tests |
| Celery worker launches a local process | Worker supervision is an isolated three-node graph community | `backend/app/services/celery_worker_supervisor.py` | Benign, governed boundary | Local filesystem Celery transport needs a consumer process | Uses an allowlisted script path, Python executable argument array, fixed working directory, and no shell | Preserve command-array and lifecycle tests |

## Healthy Signals

- `OpenDataLoaderDocumentParser` owns schema conversion and provenance; ingestion consumes only
  normalized parser data.
- `ChunkStoreService.publish_chunks` verifies returned identifiers and user/document metadata
  before marking chunks indexed.
- The OpenDataLoader-to-topic-index integration test proves source documents, page keys,
  keywords, parser metadata, and topic edges reach the knowledge graph.
- Docker and Render distinguish process readiness from ordinary health and preserve data on a
  persistent mounted disk.

## Workflow Gaps

- No checked-in CI workflow enforces backend tests, frontend build, or a clean Docker build.
- The repository uses unpinned caret ranges in the frontend manifest; this is not part of the
  migration repair, but a lockfile/CI install policy should govern future dependency updates.

## Highest-Risk Clusters

- **Embedding index storage:** model identity and dimensionality must be a single runtime
  contract because a mismatch invalidates every vector and topic projection.
- **PDF ingestion parsing:** raw extraction must remain isolated from chunk/graph policy; do
  not add OCR or parser-specific fields outside the parser boundary.

## Likely Root Causes

- Solution-first migration work split a single embedding contract between configuration,
  client behavior, and persisted index metadata.
- Deterministic trust in external provider payloads allowed broad exception handling and
  silent stream-event loss to survive.

## Permanent Fixes Applied

- Added a canonical `EmbeddingRuntime` contract shared by index initialization and the client.
- Added deterministic cloud-embedding schema validation and narrowed retry behavior to
  transport failures.
- Replaced silent SSE error swallowing with explicit parsing failure logging.

## Anti-Slop Gates

- Add CI that runs `python -m pytest -q` in `backend`, `npm run build` in `frontend`, and a
  Docker build when Docker is available.
- Require a test for each migration boundary: parser output, index contract, and provider
  protocol validation.
- Treat Graphify scanner output as triage; require source evidence before changing code or
  assigning a risk score.

## Validation

- `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown` — completed as triage before source review.
- `python -m pytest -q tests/test_nvidia_client.py` — 8 passed.
- `python -m pytest -q` — 94 passed.
- `python -m compileall -q app` — passed.
- `npm run build` — passed; Vite reports an existing 688 KB minified workbench chunk warning.
- `git diff --check` — passed after the audit edits.
- Docker build remains unverified because the local Docker daemon is unavailable.
