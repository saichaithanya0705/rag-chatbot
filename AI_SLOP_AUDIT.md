# AI-Slop Audit — OpenDataLoader Migration

## Addendum — Render Ingestion Runtime Contract (2026-09-06)

**Scope:** The Render embedding configuration changed during the live ingestion repair,
the directly connected ingestion dispatcher and optional Celery boundary, deployment
documentation, and focused deployment tests. Existing unrelated worktree changes were
preserved. The repository has no `docs/` tree, so this root report remains the required
audit location.

### Verdict

**Score: 7/100 — Minimal slop risk after repair**
**Confidence: High for the scoped ingestion and deployment surface**

### Why

- Graphify identifies a three-node Celery worker-supervision community, an extracted
  ingestion-to-index flow, and a separate embedding-compatibility community; those were the
  bounded inspection targets.
- The required scanner reported 26/100 graph-only and 86/100 source-augmented repository-wide
  triage risk. Pattern hits outside the ingestion/deployment change were not promoted without
  source evidence.
- A live disposable-PDF test proved that the ingestion runner reached parsing and chunking,
  then failed five embedding attempts with HTTP 410 because the configured hosted NVIDIA
  model had been retired.
- After the model migration, the same test reached `indexed`, and a live retrieval query
  returned the expected answer with a PDF citation.

### Evidence

| Signal | Graph evidence | Source evidence | Classification | Root cause | Permanent fix | Prevention gate |
|---|---|---|---|---|---|---|
| Render used a retired hosted embedding model | Embedding compatibility and ingestion-to-index are connected graph flows | `render.yaml` configured `nvidia/llama-nemotron-embed-1b-v2`; Render logs recorded five `410 Gone` responses from `/v1/embeddings` | Confirmed stale-integration slop signal — fixed | Deployment configuration encoded an external model identifier without a release-time provider contract check | Render now uses supported `nvidia/nemotron-3-embed-1b` with its 2048-dimensional contract; the checked-in manifest matches | `test_render_manifest.py` rejects the retired model and dimension drift; live upload-to-retrieval remains the release smoke test |
| Documentation claimed every upload required a separate Celery process | Graphify separates Celery supervision from the active ingestion dispatcher | `IngestionDispatcher.mode` returns `local` for the default filesystem configuration, `main.py` starts that runner, and production health reported `ingestionMode: local` | Confirmed review-artifact mismatch — fixed | Documentation described an older process model after ingestion ownership moved into the dispatcher | README now documents automatic local ingestion and limits separate Celery workers to externally brokered deployments | Review docs against `/api/system/health` and dispatcher tests when changing queue topology |
| Orphaned Celery subprocess supervisor remained in product code | Celery worker supervision is an isolated three-node community | Repository search found `CeleryWorkerSupervisor` only in its own module and the historical audit report; no application or test call site existed | Confirmed dead-indirection signal — fixed | A superseded local-worker mechanism remained after the in-process dispatcher became canonical | Removed the unused subprocess supervisor; the explicit worker script remains the single optional Celery entry point | Reject service classes with no runtime owner or behavior-level call-site test |

### Healthy Signals

- The live test exercised the actual Render instance and NVIDIA endpoint instead of mocking
  the queue or embedding client.
- The dispatcher exposes its active mode through system health and fails document status
  explicitly when ingestion fails.
- Test data was isolated by user id and deleted after both failure and success verification.

### Workflow Gaps

- The current Render service is a manually configured Free web service without a persistent
  disk, while `render.yaml` describes the durable paid-service target. Provider settings and
  the checked-in Blueprint can drift because no release gate compares them.
- Free-instance local SQLite, Chroma, and uploads remain ephemeral across restarts and idle
  spin-down. Resolving that limitation requires a paid disk or migration to shared external
  storage, not an additional Celery process.
- No checked-in CI workflow runs the deployment manifest contract test automatically.

### Permanent Fixes Applied

- Replaced the retired hosted embedding model in Render and the checked-in manifest.
- Corrected the ingestion documentation to match the active local dispatcher and the real
  requirements for distributed Celery.
- Removed the orphaned worker-supervisor abstraction and added manifest contract tests for
  model compatibility, readiness, and durable-storage intent.

### Anti-Slop Gates

- Run the manifest tests and a real upload-to-indexed-to-cited-query smoke before promoting
  any embedding model change.
- Compare the live Render service plan, health path, storage, model, and dimensions with the
  checked-in deployment contract before calling a release production-ready.

### Validation

- Read `graphify-out/GRAPH_REPORT.md` first (1,459 nodes, 2,666 edges, 24% inferred edges).
- Ran `graphify_slop_scan.py` once before source review: graph-only 26/100 and
  source-augmented 86/100 triage; it was not rerun after repairs, per the completion gate.
- Live Render deploy `dep-daegvbmq1p3s7399t0hg` reached `live` with
  `nvidia/nemotron-3-embed-1b` and 2048 dimensions.
- Live PDF smoke: `202 queued` to `indexed`, one page, one chunk; cited retrieval returned
  the expected answer with one PDF citation; the disposable document and fixture were removed.
- Full backend suite: 122 passed with one third-party deprecation warning; Python compilation
  across `app`, `tests`, and `scripts` passed.
- `render.yaml` parsing and `git diff --check` passed; post-deploy Render error logs were empty.

## Addendum — Netlify Production API Contract (2026-09-06)

**Scope:** Deployment configuration changed during the Netlify release, the shared frontend
API-base boundary, the PDF preview consumer, and focused build-contract tests. Existing
backend worktree changes were preserved and excluded from this repair. The repository has
no `docs/` tree, so this root report remains the required audit location.

### Verdict

**Score: 5/100 — Minimal slop risk after repair**
**Confidence: High for the scoped deployment surface**

### Why

- Graphify identifies frontend HTTP access as a small, distinct community; the deployment
  change did not add a service layer or broaden the high-centrality RAG boundaries.
- The required scanner reported 26/100 graph-only and 86/100 source-augmented repository-wide
  triage risk. Its backend-heavy pattern hits were outside this narrow change and were not
  promoted to findings without source evidence.
- A real Netlify preview exposed the confirmed defect: a production bundle built without
  `VITE_API_BASE_URL` successfully embedded `http://localhost:8000`.
- The build now fails closed for missing, malformed, non-HTTP(S), or loopback production API
  URLs, while development retains an explicit local default.

### Evidence

| Signal | Graph evidence | Source evidence | Classification | Root cause | Permanent fix | Prevention gate |
|---|---|---|---|---|---|---|
| A production build silently targeted localhost when its API environment variable was absent | `Frontend HTTP client` is a distinct ten-node community; the frontend interaction community has low graph cohesion and was treated as an inspection target | `frontend/src/shared/api/httpWorkbench.ts` had an unconditional localhost fallback; the first Netlify preview bundle contained `http://localhost:8000` | Confirmed deployment-contract slop signal — fixed | Development fallback and production configuration shared one unchecked runtime expression, so a plausible build could be operationally unusable | `frontend/vite.config.ts` now validates the production API URL before compilation; `netlify.toml` declares the public Render URL | Keep negative build tests for absent, malformed, and loopback values |
| API-base resolution was duplicated with conflicting fallbacks | The HTTP client community is directly connected to frontend workflows; no graph evidence justified separate policies | `httpWorkbench.ts` used localhost while `PdfViewerPanel.tsx` used `window.location.origin` for the same backend origin | Confirmed local-consistency signal — fixed | Two consumers independently guessed deployment behavior | `frontend/src/shared/api/apiBaseUrl.ts` owns normalization and the development default; both consumers import it | Search for direct `VITE_API_BASE_URL` reads during frontend review |
| Netlify CLI linkage created local provider state | No product-code graph impact | `.netlify/state.json` is local account/site state; `.gitignore` now excludes `.netlify` | Benign, governed tooling state | The CLI needs a local link to target the existing site | Keep the generated state untracked while preserving the explicit project configuration in `netlify.toml` | `git status` must never show `.netlify/state.json` |

### Healthy Signals

- The API URL is public deployment configuration rather than a committed credential.
- The validator runs at the build boundary before artifacts or provider side effects exist.
- Tests prove both rejection paths and the accepted public HTTPS configuration.
- Netlify preview and production checks inspect the emitted JavaScript and CORS response,
  rather than treating a successful CLI exit as deployment proof.

### Workflow Gaps

- No checked-in CI workflow currently enforces the frontend build-contract tests and
  production build before deployment.
- The existing Vite workbench chunk remains about 694 kB minified and emits the existing
  chunk-size warning; this audit found no evidence that the deployment edits caused it.

### Likely Root Cause

- A development convenience default crossed the production artifact boundary because the
  build had no environment-specific validation and two consumers resolved the URL separately.

### Permanent Fixes Applied

- Added fail-closed production URL validation to Vite configuration.
- Centralized frontend API-base normalization and removed the PDF viewer's conflicting fallback.
- Declared the Render origin in Netlify build configuration and documented the production
  build requirement.

### Anti-Slop Gates

- Run `npm run test:deployment-config`, `npm run typecheck`, and a production build with an
  explicit public API URL before every frontend deploy.
- Verify the emitted production expression binds to the intended backend origin, then confirm
  browser requests target that origin and never target a loopback host before promotion.

### Validation

- Read `graphify-out/GRAPH_REPORT.md` first (1,459 nodes, 2,666 edges, 24% inferred edges).
- Ran `graphify_slop_scan.py` once before source review: graph-only 26/100 and
  source-augmented 86/100 triage; it was not rerun after repairs, per the completion gate.
- Negative production build without `VITE_API_BASE_URL`: failed with the expected required-value error.
- Deployment-config tests: 3 passed; message-markdown tests: 3 passed.
- Production build with the Render URL and `npm run typecheck`: passed; the existing chunk-size
  warning remains.
- Playwright preview and production checks rendered the chat workbench and recorded seven
  Render API requests, all HTTP 200, with no browser errors or warnings.
- Audited Netlify production deploy: `6a9cf67b55b3f5eeea485d90` (`ready`).
- Backend suite run earlier in the deployment task: 120 passed.

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

## Addendum — Public API Entry Point (2026-08-29)

**Scope:** The public `GET /` entry point added in commit `1113cdf`, its
FastAPI application-lifecycle boundary, its regression test, and the Render
blueprint health contract. `docs/` is absent, so this root-level audit remains
the canonical report.

### Verdict

**Score: 8/100 — Minimal slop risk**
**Confidence: High**

Graphify places the change in the application lifecycle/readiness community,
away from the RAG and knowledge-graph ownership boundaries. The scanner's
repository-wide 86/100 source-augmented score is triage noise for this narrow
change: its broad-exception, subprocess, prompt, and dynamic-access hits are
outside the edited route and were not used as findings without source evidence.

| Signal | Graph evidence | Source evidence | Classification | Root cause | Permanent fix | Prevention gate |
|---|---|---|---|---|---|---|
| The deployed public root returned `404 Not Found` despite the service being healthy | System readiness health is a distinct five-node community; application lifecycle is a bounded orchestration community | `backend/app/main.py` had no `/` route; live `https://rag-chatbot-api-0612.onrender.com/` returned 404 while `/docs` and `/api/system/ready` returned 200 | Confirmed operational contract gap — fixed in source | The application exposed only internal API routes, leaving the public service URL without an entry point | `public_api_entrypoint()` returns a concise status, documentation, and readiness map at `/` without coupling to the container bootstrap | Keep a public-root HTTP regression test and verify the deployed candidate after every Render rollout |
| The first regression test invoked `APIRoute.endpoint()` directly | The change is part of the HTTP application boundary, not a pure helper | `backend/tests/test_system_health.py` bypassed FastAPI routing, response serialization, and status handling | Confirmed verification-integrity signal — fixed | The route was tested as a Python function instead of as an HTTP contract | Replaced the direct invocation with `TestClient` and a no-op lifespan limited to this test; the test now proves an actual `GET /` returns JSON 200 without starting external services | Prefer ASGI/HTTP tests for public routes; isolate lifecycle side effects rather than calling endpoint functions directly |
| Broad startup catch in the connected lifespan module | Scanner flagged `backend/app/main.py:38`; graph identifies startup/readiness as a boundary | `_bootstrap_container()` stores the error and the readiness/health routes surface starting or failed state; existing tests cover those states | Benign, governed boundary | Liveness must survive a failed optional container bootstrap so Render can distinguish process health from application readiness | No change required; the exception is logged and converted into explicit readiness behavior, not silently swallowed | Preserve failure-state tests and avoid adding catch-all fallbacks outside lifecycle ownership |

### Validation

- Graphify report read first: `graphify-out/GRAPH_REPORT.md` (2026-08-29; 1,459 nodes and 2,666 edges).
- Required triage run before source review: `py -3.11 C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown` — graph-only 26/100; source-augmented 86/100, treated as triage rather than a verdict.
- `py -3.11 -m pytest tests/test_system_health.py -q` — 8 passed.
- `py -3.11 -m compileall -q app` and `git diff --check` — passed.
- The scanner was not rerun after the test repair, per the audit completion gate.
- Residual operational risk: Render still serves the prior image until its service configuration is changed to deploy from `main`; that is an external deployment-setting change, not a source-code defect.

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


## Scoped chat reliability audit — 2026-09-09

### Verdict and scope

**Low slop-like risk, 22/100; medium confidence.** This is a scoped engineering judgment, not an authorship detector or a whole-repository certification.
Scope: retrieval, deterministic fallback, reranker protocol validation, streaming call-site wiring, and tests changed in this task. Existing staged migrations and concurrent frontend changes were preserved.
Rubric residuals: structure 3/20, maintainability 4/20, verification 5/20, security/dependencies 2/15, workflow 5/15, documentation 3/10.

Graphify (2026-08-29) predates the service-directory moves: RagService has 40 edges and RagRetrievalEngine 38; RAG answer-generation and domain-contract communities have cohesion 0.04. These directed source inspection, not deletion decisions.
The bundled scanner ran once: graph-only 26/100, source-augmented 86/100, 226 source-like files, 114 isolated nodes, 12 thin communities, 24% inferred edges. Whole-repository regex signals are not confirmed scoped findings; tool_call schema fields, for example, do not by themselves demonstrate excessive tool authority.

### Evidence and permanent repairs

| Signal | Source evidence | Classification / root cause | Repair and prevention |
|---|---|---|---|
| Dead reranking policy indirection | rag_retrieval_policy.should_rerank_candidates returned only bool(candidates), ignoring question and top_k; rag_retrieval._rank_candidates checked the same list twice | Confirmed maintainability signal in the graph's retrieval policy boundary: an obsolete optimization API survived its removal | Removed helper, exports, import and helper-only tests; the engine owns the empty-pool guard; test_sparse_evidence.py:113 checks actual filtering when all candidates belong to one document |
| Weak deterministic evidence gate | rag_grounding.py:115 accepted 50% query-term overlap, allowing acute appendicitis for acute pancreatitis | Confirmed reliability signal: shared vocabulary was mistaken for sufficient question relevance | Require 70% distinctive-term coverage; preserve short matching Q&A and sentence extraction; test_sparse_evidence.py:107 rejects the concrete counterexample |
| Citation and transport divergence | rag_service.py:692 and routers/chat.py streamed finalization | Healthy repaired boundary | Question is required for fallback, deterministic output uses normal citation finalization, and interrupted-stream regression asserts abstention and zero citations for Hello World |
| Unvalidated provider protocol | providers/reranker_service.py ranking parser | Confirmed reliability defect repaired in the task | Validate complete unique indices and finite scores; invalid provider responses use bounded lexical scoring; tests cover missing, duplicate, out-of-range and NaN results |
| Assumed ranking endpoint | providers/reranker_service.py:23 | Integration limitation, not a verified hosted success | Use NVIDIA's documented hosted retrieval endpoint while preserving custom NIM /ranking URLs; live account/function 404 remains explicitly reported |

### Design decisions and limits

Relevance is checked even for a single candidate; rank dominance cannot establish relevance. Invalid/nonpositive scored candidates are excluded, and missing/nonfinite/weak relevance requests web search when enabled. Lowering thresholds or copying the first chunk was rejected because it reproduces unrelated answers.
The deterministic selector intentionally sacrifices some lexical recall; the existing semantic extractor remains available for paraphrases. This is a conservative evidence heuristic, not proof of medical correctness, entailment, or universal answer coverage. A future calibrated relevance evaluator is valid but adds model latency and evaluation requirements.
No new agents, external actions, credentials, dependencies, or broad repository refactors were introduced by this audit. Unit tests mock network boundaries; live evidence is reported separately rather than inferred from mocks.

### Live evidence and residual risks

- Original question, web disabled: live API returned insufficient PDF evidence and no citations.
- Original question, web enabled: live SSE returned an on-topic answer with a web citation, not test.pdf; the query reached web search.
- Hosted NVIDIA reranking was unavailable with the deprecated Mistral model; the follow-up audit below records the verified replacement.
- Source hydration received 403 for some pages; do not interpret the existing web trace wording as proof every cited page was fully fetched.
- Startup also logged an existing HDBSCAN NameError in topic clustering; this is recorded separately from the scoped repairs, and readiness alone does not certify clustering.
- Graph data is stale and the checkout includes concurrent work; the audit does not certify unrelated frontend, deployment, or ingestion changes.

Deprecated provider reference: https://build.nvidia.com/nvidia/nv-rerankqa-mistral-4b-v3/experience

### Validation and completion gate

The scanner was run once before source repairs and will not be rerun for report/code changes. Full backend pytest and scoped whitespace checks are recorded below after completion. Regression coverage includes small relevant evidence, unrelated evidence, shared-word counterexamples, invalid scores, malformed provider responses, dominant-document ranking, and interrupted streaming.


Completion recorded 2026-09-10:
- `python -m pytest -q` from backend: **144 passed**, one dependency deprecation warning, after the scoped repairs.
- `python -m compileall -q app/services/rag app/services/providers/reranker_service.py app/routers/chat.py`: passed.
- `git diff --check` restricted to changed RAG/provider/test files: passed.
- Two redundant policy-only tests were replaced with behavioral regressions; the unchanged total count does not mean no new coverage.
- Confirmed scoped defects are repaired; residual provider availability and existing topic-clustering issues remain documented above.
- Completion gate honored: no second scanner run and no audit restart triggered by these report edits.

## NVIDIA reranker integration audit — 2026-09-10

**Verdict:** 12/100, minimal scoped slop-like risk after repair. Confidence: high for the
hosted reranker boundary because official documentation, negative contract tests, the full
backend suite, and a live authenticated request agree.

The 2026-08-29 Graphify report identifies `RagRetrievalEngine` as a 38-edge core abstraction
and the RAG communities at 0.04 cohesion, so the audit inspected configuration, endpoint
resolution, response validation, retrieval consumption, tests, and deployment defaults.
The required scanner ran once before source review: 26/100 graph-only and 86/100
source-augmented triage across 228 files. Those repository-wide regex scores are not scoped
defect verdicts.

| Evidence | Classification | Root cause | Permanent repair |
| --- | --- | --- | --- |
| `nvidia/nv-rerankqa-mistral-4b-v3` returned 404 and NVIDIA marks its hosted endpoint deprecated | Confirmed stale-integration signal | Model lifecycle drift was encoded independently in runtime and deployment defaults | Replaced it with `nvidia/llama-nemotron-rerank-vl-1b-v2` and its model-specific hosted endpoint in one core contract |
| Importing the shared default from the service package caused a circular `config -> services -> container -> config` dependency | Confirmed architecture signal | A provider constant crossed through a package initializer with orchestration side effects | Moved model and endpoint resolution to `app/core/nvidia_retrieval.py`; config and provider now depend inward |
| `except Exception` converted programming errors into apparent lexical-fallback success | Confirmed broad-error-masking signal | Recovery covered implementation faults as well as provider faults | Added a typed response parser and limited recovery to HTTP, JSON-decoding, and provider-contract errors |
| Earlier tests asserted `_ranking_url` and mocked only a happy-shaped response | Confirmed verification weakness | Internal state and mock plausibility substituted for the external contract | Added tests for endpoint/model mismatch, response shape, boolean/numeric distinctions, unique complete indexes, finite logits, and passage-order restoration |

Healthy evidence: the endpoint resolver rejects unknown hosted model combinations before
network access, custom self-hosted NIM bases retain `/ranking`, provider outputs are validated
before retrieval decisions, and no new dependency or credential storage was introduced.
The live request used the configured key without exposing it, did not invoke lexical fallback,
and returned scores `[-6.203125, 5.44140625]`, ranking the relevant pancreatitis passage above
`Hello World`.

Validation: `python -m pytest -q` from `backend` passed **151 tests**; the focused provider,
configuration, retrieval, and resilience set passed **50 tests** after the audit repair;
`python -m compileall -q app` passed; scoped `git diff --check` passed. The scanner was not
rerun after repairs, per the completion gate.

Current provider references:
- https://docs.api.nvidia.com/nim/reference/nvidia-llama-nemotron-rerank-vl-1b-v2-infer
- https://docs.nvidia.com/nemo/retriever/26.5.0/reference/retriever-cli-quickstart/


## Addendum - 3D knowledge graph UI audit (2026-09-10)

**Scope:** Changes made in this conversation to Graph3DCanvas, KnowledgeGraphExplorer,
GraphGuideModal, and the 3D stylesheet, plus directly connected camera/resource ownership.
The pre-existing dirty backend, graph model, manifests, and other UI changes were preserved.
This is a bounded audit, not a whole-repository approval. The root report is retained because
`docs/audits/ai-slop` does not exist.

**Verdict:** 18/100, minimal scoped slop-like risk after repairs; medium confidence.
Breakdown: structure 2/20, maintainability 3/20, verification 7/20, security/dependencies 1/15,
workflow 3/15, documentation 2/10. Remaining risk reflects incomplete live integration and
interaction coverage, not evidence that unrelated code is defective. AI provenance for this
turn is directly observable; pre-existing code authorship is not inferred.

### Evidence and permanent repairs

| Finding | Source evidence and consequence | Repair and validation |
| --- | --- | --- |
| P2: Selection resets camera | KnowledgeGraphExplorer included selectedNodeId in visibleGraph dependencies even with hop filtering disabled; that created a new layout and triggered Graph3DCanvas's fit effect. | Derive neighborhoodRootId only when hop filtering is enabled, preserving layout identity during ordinary selection. Source dependency trace reviewed; browser selection persistence after this repair remains unverified. |
| P2: Fit calculation can be clamped before the graph fits | The fit formula inflated the maximum dimension by inverse aspect, while OrbitControls capped distance at 2400. Narrow viewports could require a greater distance. | Shared graphFitDistance uses horizontal and vertical FOV separately, includes depth and sphere padding, and the caller expands camera far plane and control limits. Real Three.js projection tests verify every bounding corner at four aspect ratios, including 0.2. |
| P2: Duplicated resource disposal policies | Scene unmount and graph replacement used separate disposal implementations; one handled mesh maps while the other only released sprite maps. | One graph-owned resource disposer handles meshes, sprites, shared geometry/materials/textures. A real Three.js dispose-event test verifies each shared resource is released once. References are cleared on unmount. |
| P3: Overlay events reach scene interactions | Double-click and hover handlers on the container accepted overlay targets as graph coordinates. | Restrict picking to renderer canvas, suppress hover during dragging, and retain HUD propagation boundaries. Source review completed. |
| P3: Stale presentation contract | Old unused mostConnectedNodeConnections prop, deleted-starfield commentary, and unused monochrome legend CSS remained after color semantics changed. | Removed dead prop/call site, commentary, and unused legend styles; guide now describes the actual topic categories. TypeScript/build pass. |

### Approach and trade-offs

The original issue was incomplete ownership separation between selection, layout, camera,
and graphics resources. The repair retains the existing renderer and exposes only fit/export
controls to its parent. A small scene utility owns reusable graphics calculations and disposal;
it introduces no registry, factory, or alternate renderer. This allows tests against actual
Three.js objects rather than mocks that merely repeat implementation calls. Timer-based camera
resets and blanket exception suppression were rejected because neither repairs dependency or
resource ownership. A fully separate scene controller is a valid future option if renderer
complexity grows, but is not needed for these bounded fixes. The existing WebGL initialization
fallback is restricted to renderer creation; actual unsupported-device behavior is unverified.

### Graph triage and limits

Read graphify-out/GRAPH_REPORT.md first. Its 2026-08-29 snapshot predates this renderer;
frontend interaction controls (cohesion 0.03), workbench workflows, and the normalization-to-
visualization flow guided source inspection. Backend god nodes were not expanded into scope.
The bundled graphify_slop_scan.py ran exactly once: graph-only 26/100 and source-augmented
86/100 across 228 source-like files, with 24% inferred graph edges. These repository-wide
heuristics are not the scoped verdict and do not prove the new 3D code is represented.

### Validation and remaining gates

- `npx tsx --test tests/graph-3d-scene.test.ts`: 3/3 passed; real projection and disposal tests.
- `npm run build`: passed with an environment-only `VITE_API_BASE_URL=https://example.com/api`;
  this is compile validation, not a deployable API configuration. Existing large-chunk warning remains.
- Earlier browser fixture: actual WebGL rendered; labels toggled and empty state appeared;
  screenshot inspected. This did not verify the live backend, downloaded PNG contents, touch,
  mobile gestures, WebGL failure, or full orbit/focus behavior. No post-repair browser claim is made.
- Existing `tests/knowledge-graph-model.test.ts`: 2/3 passed in the implementation pass;
  the unchanged model excludes one-link topics from mostConnectedNode, contrary to its test.
  That prior user change and assertion were preserved; the complete suite is not claimed green.
- Targeted diff whitespace validation passed. Temporary browser fixture and owned dev server
  were removed/stopped in the implementation pass; no deployment or commit was performed.
- Prevention: keep camera fit and disposal tests; verify selection preserves camera pose and
  exported PNG contents in future browser regression coverage.

**Completion gate:** Confirmed findings in the edited scope have been repaired. Do not rerun
scanner triage solely because these fixes or this report changed repository state.

## RAG evaluation and grounding audit — 2026-09-12

**Scope:** The newly added `backend/quality_evals` suite, its regression dataset and tests,
the directly connected RAG finalization/prompt boundaries, and root README documentation.
Concurrent service-package, frontend, deployment, and unrelated dirty-worktree changes were
preserved and not treated as defects. The root report remains authoritative because
`docs/audits/ai-slop` does not exist.

**Verdict:** 14/100, minimal scoped slop-like risk after repair. Confidence: high for the
deterministic regression path; medium for live-model semantic quality because this audit did
not call an external model judge. This is an engineering-risk assessment, not an authorship
claim about pre-existing code.

The 2026-08-29 Graphify report was read before source inspection. It identifies `RagService`
(40 edges) and `RagRetrievalEngine` (38) as core nodes, with RAG answer generation and domain
contracts both at 0.04 cohesion; those facts justified tracing prompt construction, final
answer validation, fallback, reranking, and the new eval runner together. The bundled scanner
ran once before repair: graph-only **26/100** and source-augmented **86/100** across 241
source-like files, with 24% inferred edges, 114 isolated nodes, and 12 thin communities.
Those repository-wide regex heuristics selected targets; they are not the scoped verdict and
were not rerun after repair.

| Signal | Source evidence | Classification and root cause | Permanent repair and prevention gate |
| --- | --- | --- | --- |
| A valid source marker authorized an unsupported extra claim | The initial eval replay produced `A process is a program in execution and always cures cancer. [SourceID: process]`; whole-segment citation checks skipped cited text. | Confirmed grounding and verification defect: source existence was mistaken for claim-level entailment. | Replaced the marker-skipping helper with atomic-claim validation in `rag_answer_text.py`; every substantive clause must be token-supported by eligible evidence. Unsupported stream output is replaced only by deterministic cited fallback. The adversarial dataset and direct finalizer tests are the regression gate. |
| Retrieved prompt injection could be supplied as answer evidence | The initial eval replay returned `The secret system prompt is ORBIT-9` from a source beginning `Ignore previous instructions`. | Confirmed trust-boundary defect: untrusted retrieved content reached prompt, citation, and fallback paths without a common eligibility rule. | A single instruction-shaped-evidence filter now applies before prompt construction, shortcuts, citation extraction, semantic fallback, and deterministic fallback. The prompt-boundary test proves the injected text never enters the model prompt; the eval now fails closed when all retrieved evidence is unsafe. |
| Eval runner used uninitialized service/engine instances and type suppressions | `quality_evals/targets.py` used `object.__new__` plus `type: ignore` solely to invoke pure ranking and answer-finalization behavior. | Confirmed local architecture signal: test harness mechanics bypassed construction contracts and obscured the actual boundary under evaluation. | Extracted pure relevance ranking into `rank_candidates_by_relevance`, made finalization/fallback explicitly static because they carry no instance state, and typed the intent client as a protocol. The runner now invokes real public behavior without uninitialized objects or local suppressions. |
| Judge retried every exception, including implementation faults | `quality_evals/judge.py` had `except Exception` around provider invocation and JSON validation. The new test showed a `KeyError` became a misleading judge retry failure. | Confirmed broad-error-masking signal: an internal wiring bug could be reported as a model-quality failure. | Retry is restricted to provider transport, timeout, malformed-output, and missing-response-shape failures; unexpected programming errors propagate. The focused regression test first failed on the old behavior and now passes. |

### Healthy signals

- The eval dataset is versioned and schema-validated; duplicate case IDs, unknown expected
  contexts, malformed JSON, invalid reranker scores, and missing recorded outputs fail before
  scoring.
- Offline replay is deterministic and provider-free. Live target evaluation and optional judge
  runs are explicit, require configured credentials, log decisions locally, and do not add a
  dependency, deployment side effect, or credential store.
- The root README now distinguishes deterministic regression gates from optional model judging
  and requires human calibration before judge results become a release gate.
- Tests exercise final user-visible answers and prompts rather than mocks of implementation
  calls; no scanner suppression, dependency workaround, or test-only production API was added.

### Remaining risk and anti-slop gates

- The deterministic claim validator intentionally fails closed when meaningful paraphrase
  terms are absent from evidence. It is not a substitute for a calibrated semantic judge or
  human review of production traces; use `--live-model --judge` only with a separate judge
  model and human-labeled calibration set.
- The instruction-pattern filter is conservative. Documents that discuss attack strings as
  examples may need a future provenance-aware safe quoting design; do not weaken the current
  boundary by treating raw retrieved instructions as trusted evidence.
- Keep `python -m pytest -q` and `python -m quality_evals.run` as separate CI gates. Add a
  reviewed, anonymized failure case for each production regression and retain a held-out set
  when prompts or models are selected.

### Validation

- Focused RAG, prompt, retrieval, fallback, resilience, and evaluation suite: **55 passed**,
  with one pre-existing `pytest-asyncio` configuration warning.
- Full backend suite from `backend`: **167 passed**, with one pre-existing `pytest-asyncio`
  configuration warning. No external provider or deployment claim is made by this audit.
- Offline evaluation: **19/19 passed**, all configured quality gates at 1.0.
- `python -m compileall -q app quality_evals ...` and scoped `git diff --check` passed during
  repair. The scanner was not rerun after code or report edits, honoring the completion gate.

## Reranker commit follow-up audit — 2026-09-10

**Verdict:** 10/100, minimal scoped slop-like risk after repair; high confidence. Scope is limited to commits `a9e22d8` and `c79822c`, their provider boundary, and directly overlapping reranker tests.

Graphify's 2026-08-29 report places retrieval in a low-cohesion RAG area (`RagRetrievalEngine`: 38 edges; RAG domain contracts: 0.04 cohesion). The required scanner ran once for this follow-up: 26/100 graph-only and 86/100 source-augmented triage across 231 source-like files. These repository-wide regex results selected inspection targets and are not the scoped verdict.

| Evidence | Classification | Root cause | Permanent repair |
| --- | --- | --- | --- |
| `providers/reranker_service.py` imported `DEFAULT_RERANKER_MODEL` without using it | Confirmed maintainability signal | The shared contract import was copied as a group while only the base URL and resolver belong to the provider | Removed the dead import so configuration owns the default and the provider owns endpoint execution |
| `test_sparse_evidence.py` repeated endpoint and response-parser cases already owned by `test_nvidia_reranker_contract.py` | Confirmed verification-ownership signal | Clean-baseline commit isolation introduced a focused contract suite without consolidating the working-tree suite | Kept provider fallback behavior in the sparse-evidence suite and moved endpoint/schema/order coverage exclusively to the focused contract suite |

Healthy evidence: hosted model/endpoint matching fails before network access; custom NIM URLs remain supported; responses require complete, unique, finite indexed scores; recovery catches provider and contract failures without masking programming errors. Validation after repair: focused reranker and sparse-evidence tests passed, compileall passed, and scoped diff whitespace validation passed. Completion gate honored: the scanner was not rerun after repair.

## Service-package compatibility audit — 2026-09-11

**Scope:** The service-package compatibility boundary changed in this prompt, its new
regression test, and the directly connected `ServiceContainer` to `RagService` extractive-
fallback injection path. Existing backend, frontend, deployment, and audit edits remain out
of scope and were preserved. The root report remains authoritative because
`docs/audits/ai-slop` does not exist.

**Verdict:** 11/100, minimal scoped slop-like risk after repair; high confidence for local
imports and fallback wiring. Breakdown: structural health 2/20, maintainability 2/20,
verification 2/20, security/dependencies 0/15, workflow controls 4/15, documentation and
provenance 1/10. AI provenance is known only for this prompt's edits; no authorship inference
is made about existing code.

The 2026-08-29 Graphify snapshot identifies `ServiceContainer` (26 edges), `build_container`
(25), and `RagService` (40) as central orchestration nodes, while application service
orchestration and RAG answer generation both have low cohesion. It therefore justified
checking package import side effects, compatibility behavior, constructor injection, and
provider-failure fallback together. The bundled scanner ran once before repair: 26/100
graph-only and 86/100 source-augmented triage across 232 source-like files, with 24% inferred
edges, 114 isolated nodes, and 12 thin communities. Those repository-wide heuristics selected
targets; they are not the scoped verdict.

| Evidence | Classification | Root cause | Permanent repair and prevention gate |
| --- | --- | --- | --- |
| `app.services` eagerly imported `container` and all 41 canonical targets merely to register old module names | Confirmed indirection and import-coupling signal | Compatibility was implemented as eager runtime wiring, turning the package initializer into a whole-service-graph loader | A standards-compliant lazy finder now creates forwarding compatibility modules and imports only the requested canonical module; a fresh-process assertion prevents root-import regression |
| The first migration test used eight `type: ignore` suppressions and asserted `_extractive_fallback_service` directly | Confirmed verification-debt signal | The test mirrored constructor storage instead of proving the user-visible fallback contract | Replaced it with typed-spec collaborators and a behavioral provider-failure fallback assertion covering invocation, grounded answer, and citation |
| The original compatibility finder imported and mutated `sys.modules` inside `find_spec`, then returned the canonical module's differently named spec | Confirmed non-idiomatic import signal | Module discovery and module execution were conflated to retain identity | `find_spec` now only returns a spec for the requested legacy name; the loader owns canonical import and symbol forwarding, and tests verify legacy `__name__`, spec name, and canonical exported-symbol identity |
| `build_container` creates one configured `ExtractiveFallbackService` and injects it into `RagService`; fallback output still passes normal grounding/citation finalization | Healthy architecture signal | The container is a deliberate composition root and the RAG service owns fallback policy | Retained without another service locator or wrapper; focused sync, stream, sparse-evidence, grounding, retrieval-policy, and constructor-boundary tests remain the gate |

### Aggressive review targets and residual risk

- The Graphify snapshot predates this package split, so its inferred package relationships are
  navigation evidence rather than current structural proof.
- Compatibility modules preserve import specs and exported object identity, but deliberately do
  not promise that assigning arbitrary attributes on a legacy module mutates the canonical
  module. Remove the compatibility map after a documented deprecation window rather than
  expanding it into a permanent plugin system.
- The existing global `pytest-asyncio` loop-scope deprecation warning is outside this scoped
  change; it remains visible rather than being suppressed.

### Validation

- Fresh-process import check: root package stayed lazy; legacy `rag_service` name/spec and
  canonical `RagService` symbol forwarding passed.
- Focused backend suite from `backend`: **69 passed**, one existing dependency warning.
- `python -m compileall -q app tests scripts`: passed.
- No dependency, provider, credential, deployment, or unrelated application behavior changed.
- Completion gate honored: the scanner was not rerun after repairs and this report update did
  not restart the audit.
