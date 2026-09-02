# AI-Slop Audit — OpenDataLoader Migration

## Addendum — Parser and Chat Reliability (2026-09-01)

**Scope:** Changes made to repair the OpenDataLoader-to-index pipeline, local embedding
startup, synchronous and SSE chat generation, evidence fallback, and directly connected
tests and documentation. The repository has no `docs/` tree, so this root report remains
the required audit location.

### Verdict

**Score: 11/100 — Minimal slop risk**
**Confidence: High**

### Why

- Graphify places `RagService` at a high-centrality grounded-answer boundary and separates
  PDF parsing, embedding compatibility, and chat delivery into recognizable communities.
- The required scanner reported 26/100 graph-only risk and 86/100 source-augmented triage
  risk. Source inspection rejected pattern-only hits such as typed `prompt` parameters,
  bounded retry delays, and the allowlisted Celery subprocess as findings.
- Confirmed fallback duplication, unreachable generation state, missing stream option
  propagation, broken shared-cache behavior, and failure-path test gaps were repaired at
  their owning boundaries.
- Model output is buffered and grounding-validated before SSE delivery; evidence fallback
  produces citations, while provider failures without evidence fail closed.

### Evidence

| Signal | Graph evidence | Source evidence | Classification | Root cause | Permanent fix | Prevention gate |
|---|---|---|---|---|---|---|
| Provider and interrupted-stream failures escaped even when retrieved evidence was available | `RagService` bridges RAG generation, retrieval citations, and chat delivery; grounded chat is an extracted hyperedge | `backend/app/services/rag_service.py`, `backend/app/routers/chat.py`, `backend/tests/test_chat_pipeline_resilience.py` | Confirmed slop signal — fixed | Failure policy existed for timeouts and some ungrounded outputs but was not a complete transport-independent contract | `RagService` now owns typed fallback reasons and cited evidence composition; sync and SSE paths use the same policy and no-evidence failures still raise | Keep sync, stream, interrupted-stream, timeout, ungrounded, and no-evidence regression cases |
| SSE emitted partial provider text before grounding validation and omitted `responseLength` | Graphify identifies an SSE answer-delivery flow and a separate chat API contract | `backend/app/routers/chat.py`, `backend/tests/test_chat_pipeline_resilience.py` | Confirmed validation-boundary signal — fixed | Transport progress and untrusted model output were treated as the same event stream; one request option was dropped at the route boundary | The route emits progress/heartbeat events while buffering provider text, validates the complete answer, then emits only the finalized response; it now forwards `responseLength` | Route-level SSE tests must assert final citations, absence of error events on evidence fallback, and option propagation |
| Generation loops retained unreachable result/error tails; non-thinking ungrounded output could bypass the intended evidence fallback | `RagService` is a 40-edge god-node review target in a 0.04-cohesion generation community | `backend/app/services/rag_service.py`, `backend/tests/test_chat_pipeline_resilience.py` | Confirmed dead-state and contract signal — fixed | Retry-loop control flow had accumulated post-loop branches that no reachable attempt needed | Each attempt now returns, retries, falls back, or raises in place; unreachable state was removed and final ungrounded output deterministically uses cited evidence | Require negative tests that would fail for plausible but ungrounded model output |
| FastEmbed used a shared default cache that contained an incomplete tokenizer snapshot | Embedding compatibility safety is a dedicated graph community connected to index storage | `backend/app/core/config.py`, `backend/app/services/nvidia_client.py`, `backend/app/services/container.py`, `backend/tests/test_nvidia_client.py` | Confirmed runtime-contract signal — fixed | Model storage was implicit and outside application runtime ownership | A configurable application-owned model cache is created with other runtime directories; the exact incomplete-tokenizer failure retries once in an isolated recovery cache without deleting operator data | Run the real model verifier and keep cache-path/recovery tests |
| Parser tests covered structured happy paths but not engine failover or the final both-engine error | PDF ingestion parsing is a distinct graph community and OpenDataLoader provenance is an extracted hyperedge | `backend/app/services/opendataloader_parser.py`, `backend/tests/test_opendataloader_parser.py` | Confirmed verification-debt signal — fixed | Existing tests proved schema conversion but not the public parser failure contract | Added OpenDataLoader-to-PDFium failover and both-engine-failure tests; the broad catches remain bounded to independent parser engines and retain the final diagnostic | Keep real-PDF smoke coverage plus deterministic engine-failure unit tests |

### Aggressive Review Targets

- `RagService` remains highly central, but the inspected generation/finalization methods now
  own one cohesive policy. Future unrelated responsibilities should be extracted rather than
  added to this service.
- A second local generative ML model is technically feasible, but it is not implemented here.
  It needs an explicit resource budget, the same grounding/citation finalization gate, and
  observable provider-selection telemetry; an unconstrained second model would widen failure
  and deployment surface without improving trust.
- OCR remains intentionally unavailable. Image-only PDFs fail with an explicit capability
  message rather than silently producing an empty index.

### Healthy Signals

- OpenDataLoader output is normalized behind `DocumentParser`; chunking, Chroma publication,
  metadata provenance, and topic indexing consume the normalized contract.
- The real local pipeline parsed a two-page PDF, published two chunks, retrieved two contexts,
  and returned a grounded answer with a citation.
- The fallback is deterministic evidence composition, not a second unchecked model response.

### Workflow Gaps

- No checked-in CI workflow makes backend tests, frontend tests/typecheck/build, or model
  contract verification mandatory.
- `pytest-asyncio` reports that its future loop-scope default is not configured explicitly.

### Highest-Risk Clusters

- **Grounded answer generation:** model/provider failures must never bypass citation validation
  or expose partial unvalidated output.
- **Embedding index compatibility:** cache ownership, model identity, and vector dimensions must
  remain one runtime contract.
- **PDF ingestion:** parser-engine fallback must preserve page/provenance contracts and surface
  image-only/OCR limitations honestly.

### Likely Root Causes

- Repeated feature edits split one fallback policy between the service and SSE transport and
  left dead retry-loop state behind.
- Happy-path verification covered parser conversion and chat success but missed provider,
  stream-interruption, cache-corruption, and parser-engine failure paths.

### Permanent Fixes Applied

- Centralized evidence-fallback reasons and messages in the RAG domain boundary.
- Buffered stream output until grounding finalization and restored `responseLength` propagation.
- Removed unreachable generation-loop state and enforced no-evidence fail-closed behavior.
- Added application-owned embedding cache recovery and parser/chat negative-path tests.

### Anti-Slop Gates

- Add CI for the full backend suite, frontend tests/typecheck/build, and a dependency-controlled
  model contract smoke test.
- Keep model output behind deterministic grounding, schema, and citation validation before any
  UI delivery or side effect.
- Treat Graphify/scanner results as triage and require graph plus source evidence for findings.

### Validation

- Read `graphify-out/GRAPH_REPORT.md` first (2026-08-29; 1,459 nodes, 2,666 edges,
  24% inferred edges).
- Ran the required `graphify_slop_scan.py` once before source review: graph-only 26/100;
  source-augmented 86/100 triage. It was not rerun after fixes, per the completion gate.
- Targeted parser/chat/cache/config validation: 30 passed; final backend suite: 108 passed;
  `python -m compileall -q app tests scripts`: passed.
- Real model verifier: 384-dimensional local embedding produced and live generation returned
  `ok`.
- Real local parser-to-chat lifecycle: two pages parsed, two chunks indexed, two contexts
  retrieved, and one citation returned without warnings.
- Frontend validation: 15 tests, typecheck, and production build passed; Vite retains an existing
  688.82 kB workbench chunk warning.

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
