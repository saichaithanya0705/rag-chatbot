**Verdict**
Score: 28/100, Low slop risk
Confidence: Medium

Scope: deployment-related edits made in this prompt and directly connected architecture only: `render.yaml`, `netlify.toml`, `backend/requirements.txt`, `backend/app/core/config.py`, `backend/app/main.py`, `backend/app/dependencies.py`, `backend/app/services/docling_parser.py`, `backend/app/services/document_service.py`, `backend/app/services/document_repository.py`, `backend/app/services/nvidia_client.py`, `backend/app/routers/system.py`, `backend/app/models/schemas.py`, `backend/tests/test_config.py`, `backend/tests/test_dependencies.py`, `backend/tests/test_docling_parser.py`, `backend/tests/test_nvidia_client.py`, `backend/tests/test_system_health.py`, `frontend/src/shared/api/httpWorkbench.ts`, `frontend/tests/http-workbench-bootstrap.test.ts`, and `frontend/src/app/providers/workbench/workbenchChatActions.test.ts`.

Graphify freshness: `graphify-out/GRAPH_REPORT.md` dated 2026-05-17.

Important context: the bundled Graphify triage scanner reported `86/100` severe graph-plus-source triage risk for the whole repository. This report is narrower and only scores the prompt-touched deployment/parser/test path after source verification and repairs.

**Why**
- The prompt-touched path contained real deployment/runtime drift, not style-only suspicion: code referenced runtime dependencies that were absent from the declared backend manifest.
- The affected backend config and parser code sit in high-blast-radius areas according to Graphify: `DoclingDocumentParser` is a god node with 29 edges, and Community 5 (`Settings`, `load_settings()`, runtime directories) is a central infrastructure cluster.
- The parser capability contract had conflated “overall parser available” with “OCR-capable Docling pipeline available”, which made health reporting less truthful than the actual fallback behavior.
- The backend boot path still imported the full container and ML dependency graph during `app.main` import, and `NvidiaClient` still imported `sentence_transformers` eagerly even when the hosted NVIDIA API path was configured.
- The frontend production build was blocked by a test harness typing bug in a file compiled by the production build path.
- The confirmed issues in scope are now fixed and validated.

**Evidence**
| Signal | Graph Evidence | Source Evidence | Classification | Likely Root Cause | Permanent Fix | Prevention Gate |
|---|---|---|---|---|---|---|
| Runtime dependency drift in a core parser/config path | `DoclingDocumentParser` is god node #7 with 29 edges; Community 5 (`Settings`, `load_settings()`) is a central runtime cluster | `backend/app/core/config.py:6`, `backend/app/services/docling_parser.py:67`, `backend/app/services/docling_parser.py:97`, `backend/requirements.txt:9`, `backend/requirements.txt:10` | Confirmed slop signal | Solution-first implementation updated code paths without updating the deployment manifest | Declared `pypdfium2` and `python-dotenv` in `backend/requirements.txt` so the fallback parser and env loading exist in clean deployments | Add a clean-environment backend install/import smoke check to CI before deploy |
| Deployment state path hard-coded to the repo layout | Community 5 contains `Settings`, `load_settings()`, and runtime directory creation; this is central infrastructure, not leaf code | `backend/app/core/config.py:96-108`, `backend/tests/test_config.py:13-39` | Confirmed slop signal | Deployment config was added before storage paths were made injectable | Added `RAG_DATA_DIR` path override and kept derived storage paths (`uploads`, `sqlite`, `chroma`, `kg`, `celery`, Docling artifacts) consistent under that root | Require stateful deploy paths to be environment-configurable before adding host blueprints |
| Parser health contract collapsed two different capabilities into one flag | `DoclingDocumentParser` is a graph hub; Community 7 is the parser cluster and Community 5 is the health/config cluster | `backend/app/services/docling_parser.py:48-63`, `backend/app/models/schemas.py:8-20`, `backend/app/routers/system.py:24-36`, `backend/tests/test_docling_parser.py:174-199` | Confirmed slop signal | A single availability method was reused for both parser readiness and OCR readiness | Split capability reporting into `is_available()` for overall parsing path, `ocr_pipeline_available()` for Docling/OCR capability, and exposed `parserAvailable` separately in health response | Keep health endpoints capability-specific; do not reuse one boolean for multiple operational meanings |
| Liveness and readiness were still coupled in the hosted boot path | Graphify lists `build_container()` and `ServiceContainer` as top central nodes; Community 5 contains `lifespan()` and settings/runtime helpers, so boot-path coupling here has repo-wide blast radius | `backend/app/main.py`, `backend/app/dependencies.py`, `backend/app/routers/system.py`, `backend/app/services/document_service.py`, `backend/app/services/document_repository.py`, `backend/tests/test_dependencies.py`, `backend/tests/test_system_health.py` | Confirmed slop signal | Startup work was moved off the FastAPI lifespan critical path, but module import, health, and host health-check semantics still assumed a fully built container | Deferred container imports behind bootstrap, centralized container-state resolution, made `/api/system/health` answer during startup, added `/api/system/live` for Render process liveness, and kept business endpoints behind `503` readiness checks | Add a cold-start import timing check and a hosted-health contract test to CI before deploy |
| Parser capability probes made health heavyweight | `DoclingDocumentParser` is god node #7, and Community 7 is directly connected to parser health behavior | `backend/app/services/docling_parser.py`, `backend/app/routers/system.py`, `backend/tests/test_docling_parser.py`, `backend/tests/test_system_health.py`; local timing showed `ocr_pipeline_available()` took about `21.198s` before repair | Confirmed slop signal | Health called parser capability methods that imported the full Docling stack even when pypdfium2 fallback was enough and OCR was disabled | Reworked capability probes to use cached package discovery, made `is_available()` prefer the lightweight fallback, and skipped OCR pipeline probing from health when OCR is disabled | Health endpoints must use cheap capability discovery, not import or initialize heavyweight optional parser stacks |
| Frontend bootstrap ignored backend readiness semantics | Community 12 contains the workbench gateway and provider bootstrap path, so startup-contract drift here breaks the entire SPA rather than an isolated widget | `frontend/src/shared/api/httpWorkbench.ts`, `frontend/tests/http-workbench-bootstrap.test.ts`, Render runtime logs at `2026-06-12T13:21:09Z` showed `/api/system/health` returning `200` while `/api/documents` and `/api/kg/graph` still returned `503` | Confirmed slop signal | The frontend called workspace endpoints in parallel with health and converted transient Render wake-up/startup `503`s into a terminal workspace error screen | Added readiness polling against `/api/system/ready`, read `/api/system/health` only after readiness for metadata, and retried transient `502`/`503`/`504` startup responses instead of failing permanently | Keep liveness, readiness, and metadata health contracts separate, and add bootstrap tests that simulate cold-start startup windows |
| Hosted bootstrap still paid for local embedding fallback dependencies even on the cloud path | `build_container()` is a central graph hub, and `NvidiaClient` sits inside that boot chain | `backend/app/services/nvidia_client.py`, `backend/tests/test_nvidia_client.py` | Confirmed slop signal | `sentence_transformers` was imported at module load, so the cloud-only deployment still loaded heavyweight local embedding dependencies during bootstrap | Moved `sentence_transformers` behind a lazy helper that only imports on first local fallback use | Keep optional ML fallback dependencies behind call-time imports instead of module-level imports |
| Frontend production build depended on a brittle test harness narrowing pattern | Community 12 contains `createWorkbenchChatActions()` and workbench state helpers, so build-breaking test issues in this cluster are not isolated noise | `frontend/src/app/providers/workbench/workbenchChatActions.test.ts:82-117` | Confirmed slop signal | Mutable async callback capture was asserted as if it were synchronously narrowed, causing the production TypeScript build to fail | Replaced the brittle assertion flow with an explicit runtime guard plus typed local binding so the test matches the gateway contract and the build remains green | Keep files under `src/` build-clean, or move pure tests out of the production compilation surface |

**Aggressive Review Targets**
- `render.yaml` is structurally sound for a demo deployment, but the hosted runtime still needs post-fix verification after the latest startup changes are pushed and redeployed.
- The backend remains stateful. The new `RAG_DATA_DIR` support removes repo-coupling, but durable multi-user hosting still depends on platform storage choices outside this repo.
- The whole-repo Graphify triage remains much higher risk than this scoped pass. A separate repo-wide audit is still warranted for hotspots like `nvidia_client.py`, `rag_service.py`, and `database.py`.

**Healthy Signals**
- The repo already had meaningful parser and ingestion contract tests, and the new fixes extended that coverage instead of weakening it.
- The deployment path now has explicit host config (`render.yaml`, `netlify.toml`) rather than dashboard-only hidden state.
- The parser fallback behavior is now both implemented and reported more honestly.
- The backend import path now avoids loading the service container graph during `app.main` import; local import time dropped from about `24.45s` to `0.84s`.
- The embedding client no longer imports `sentence_transformers` unless local fallback embeddings are actually needed.
- The frontend production build succeeds after the test harness correction.

**Workflow Gaps**
- No repository-local CI workflow files were found during the scoped artifact inventory, so there is no visible clean-room install/build/test gate enforcing the deployment path.
- The frontend production build compiles tests under `src/`, which increases the chance that test-only typing regressions block deploys.

**Highest-Risk Clusters**
- `backend/app/core/config.py` and connected runtime files: central configuration has high blast radius, so deployment shortcuts here quickly become architectural debt.
- `backend/app/services/docling_parser.py`: this is a hub abstraction with fallback behavior, external dependencies, and health implications, so contract drift here is especially costly.

**Likely Root Causes**
- Solution-first deployment work that updated code and host config out of order.
- Missing fresh-environment validation gate for backend dependencies.
- Collapsed operational semantics in the parser health contract.
- Importing the full service/container graph at module load even though hosted boot only needs the ASGI app object to bind first.
- Importing heavyweight local embedding dependencies even when the deployment is configured for hosted NVIDIA embeddings.
- Test harness logic living in the production compilation path without a build-focused guardrail.

**Permanent Fixes**
- Declared missing backend runtime dependencies required by the actual code path.
- Added `RAG_DATA_DIR` so deployments can relocate state without rewriting code or binding to the repository layout.
- Split parser capability reporting into overall parser availability and OCR-pipeline availability.
- Deferred heavy container imports behind async bootstrap, separated liveness health from container readiness, and added a global indexed-chunk count for non-user health checks.
- Consolidated container-state resolution so the health route and guarded endpoints use the same startup/error semantics.
- Added a dedicated readiness endpoint for application bootstrap, added a separate liveness endpoint for Render, and changed the frontend bootstrap flow to wait for readiness instead of treating transient cold-start `503`s as a permanent failure.
- Made parser capability checks cheap and cached so health checks cannot load the full Docling stack just to report availability.
- Deferred `sentence_transformers` import until the first real local-fallback embedding call.
- Strengthened tests around config overrides and fallback capability reporting.
- Added `backend/tests/test_nvidia_client.py` so the cloud path cannot regress back to eager local model imports.
- Added `backend/tests/test_dependencies.py` so the startup/error contract cannot drift between the health route and dependency-guarded endpoints.
- Added `backend/tests/test_system_health.py` to lock the startup/ready/error health contract.
- Corrected the frontend test harness so the production build reflects real type-safe behavior.

**Anti-Slop Gates**
- Add a CI job that performs: backend dependency install, backend targeted tests, and frontend production build from a clean checkout.
- Keep health schemas capability-specific; one field should represent one operational fact.
- Require environment-overridable storage roots before adding hosted deployment blueprints for stateful services.
- Ensure the ASGI import path does not import heavyweight service graphs unless the app actually needs them to bind a port.
- Treat “code imports it” as “manifest must declare it”; review dependency manifests in the same diff as runtime changes.

**Validation**
- Stop-hook audit pass for the deployment/readiness/parser/bootstrap edits:
  - Re-read `C:/Users/SAI/.codex/skills/audit-ai-slop/SKILL.md`, re-read `graphify-out/GRAPH_REPORT.md`, and re-ran the bundled Graphify slop triage scanner.
  - Result: no new confirmed slop defect was found in the prompt-touched liveness/readiness/parser/bootstrap path; previous root-cause fixes remain the canonical repair.
- `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`
  - Result: whole-repo triage `86/100` severe risk; used as triage only, not as the final verdict for this narrower scope.
- `D:\projects\chat\backend\.venv\Scripts\python.exe -m pytest tests\test_docling_parser.py tests\test_ingestion_docling_contract.py tests\test_config.py`
  - Result: `8 passed`.
- `D:\projects\chat\backend\.venv\Scripts\python.exe -m pytest tests\test_system_health.py tests\test_ingestion_dispatcher.py tests\test_docling_parser.py tests\test_config.py`
  - Result: `11 passed`.
- `D:\projects\chat\backend\.venv\Scripts\python.exe -m pytest tests\test_nvidia_client.py tests\test_system_health.py tests\test_ingestion_dispatcher.py tests\test_docling_parser.py tests\test_config.py`
  - Result: `13 passed`.
- `D:\projects\chat\backend\.venv\Scripts\python.exe -m pytest tests\test_dependencies.py tests\test_nvidia_client.py tests\test_system_health.py tests\test_ingestion_dispatcher.py tests\test_docling_parser.py tests\test_config.py`
  - Result: `16 passed`.
- `npx tsx --test tests/http-workbench-bootstrap.test.ts` in `frontend/`
  - Result: `2 passed`.
- `D:\projects\chat\backend\.venv\Scripts\python.exe -c "import time; start=time.time(); import app.main; print(round(time.time()-start, 2))"`
  - Result: `0.84` seconds after deferring container imports; previously measured at `24.45` seconds.
- `D:\projects\chat\backend\.venv\Scripts\python.exe -c "from app.main import app; print(app.title)"`
  - Result: imported successfully and printed `Local RAG Chat Backend`.
- `npm run build` in `frontend/`
  - Result: production build passed.
- `D:\projects\chat\backend\.venv\Scripts\python.exe -m pytest tests\test_system_health.py tests\test_docling_parser.py tests\test_dependencies.py tests\test_nvidia_client.py tests\test_ingestion_dispatcher.py tests\test_config.py`
  - Result: `21 passed`.
- `npx tsx --test tests/http-workbench-bootstrap.test.ts` in `frontend/`
  - Result: `2 passed`.
- Local parser capability timing after repair: `fallback True 0.002`, `ocr True 0.001`, `is_available True 0.0`.
- `npm run build` in `frontend/`
  - Result: production build passed after the liveness/readiness fix.
- Hosted Render smoke test:
  - Result: `/api/system/live`, `/api/system/ready`, `/api/system/health`, `/api/documents`, `/api/topics`, `/api/kg/graph`, and `/api/sessions` all returned `200`.
- Hosted Netlify smoke test:
  - Result: `https://rag-chatbot-portfolio-0612.netlify.app/chat` rendered the workspace; Playwright observed bootstrap calls to Render returning `200` for readiness, health, documents, topics, graph, sessions, and session creation.

Residual risk:
- Render free-tier instances can still sleep after inactivity, so the first request after a long idle period may be slower, but the frontend now waits for readiness instead of showing a permanent workspace-load failure.

---

## Chat Intent And Document Inventory Audit Pass - 2026-06-12

**Verdict**
Score: 24/100, Low slop risk after repair
Confidence: Medium

Scope: chat intent and document-inventory edits made in this prompt plus directly connected routing/trace tests: `backend/app/services/message_intent.py`, `backend/app/services/rag_service.py`, `backend/app/services/answer_trace.py`, `backend/app/services/document_inventory.py`, and `backend/tests/test_chat_intent_and_reasoning.py`.

Graphify freshness: `graphify-out/GRAPH_REPORT.md` dated 2026-05-17.

Important context: the bundled Graphify triage scanner again reported `86/100` severe graph-plus-source risk for the whole repository. This scoped pass treats that as triage only and scores the prompt-touched chat-routing path after source inspection and repair.

**Why**
- Graphify identifies `RagService` as god node #5 with 36 edges and a cross-community bridge. Adding workspace inventory formatting directly to it would increase mixed responsibility in an already central coordinator.
- The initial chat-routing repair correctly introduced `document_inventory`, but source inspection showed response construction also belonged to a separate deterministic inventory boundary.
- The rule-first classifier had one over-broad app-help regex that could classify domain questions like "how do I use insulin from this PDF?" as conversation instead of knowledge.
- The repaired path now separates intent classification, RAG coordination, document-inventory presentation, and trace reporting.

**Evidence**
| Signal | Graph Evidence | Source Evidence | Classification | Likely Root Cause | Permanent Fix | Prevention Gate |
|---|---|---|---|---|---|---|
| Workspace inventory presentation added to an existing RAG god node | Graphify lists `RagService` as god node #5 and a bridge across RAG, retrieval, parser, web, and intent communities | Before repair, inventory formatting lived in `backend/app/services/rag_service.py`; after repair `RagService` only routes at `backend/app/services/rag_service.py:376` and delegates answer construction at `backend/app/services/rag_service.py:382` | Confirmed slop signal, fixed | Solution-first bug fix put deterministic app-state presentation into the fastest visible coordinator | Added `backend/app/services/document_inventory.py:9` with focused inventory answer construction and kept `RagService` as the routing coordinator | When adding new response modes, keep formatting/business presentation out of `RagService` unless it is RAG-specific |
| App-help regex was broad enough to swallow real domain questions | Community 17 is the intent-classification cluster; incorrect shortcuts here bypass RAG and affect all chat routes | App-help patterns now require app/document context in `backend/app/services/message_intent.py`; regression test at `backend/tests/test_chat_intent_and_reasoning.py:152` proves a domain "how do I use..." question stays on the knowledge path | Confirmed slop signal, fixed | Rule-first classifier was added without a negative boundary test for plausible overlapping language | Narrowed app-help rules and added the negative regression test | For every deterministic shortcut, add at least one near-miss test that must not shortcut |
| New document-inventory response mode needed trace separation | `build_answer_trace()` sits in Community 11 with history serialization; misleading trace output creates review/debugging ambiguity | `backend/app/services/answer_trace.py:35` returns an `inventory` trace instead of claiming scoped PDF retrieval | Healthy architecture signal | A new response mode was added, so trace semantics needed a matching branch | Added an explicit `document_inventory` trace branch and regression test at `backend/tests/test_chat_intent_and_reasoning.py:242` | New response modes must add trace assertions that prove they do not claim unrelated retrieval/citation behavior |

**Aggressive Review Targets**
- The prompt-based classifier still depends on model JSON for non-rule cases. It parses defensively and falls back to knowledge, but broader intent taxonomy should eventually be evaluated with more near-miss examples.
- Session memory lookup still happens before `RagService.prepare_answer()` in the streaming/query routes, so purely conversational turns may still pay memory-embedding cost before shortcutting. This is performance debt, not a confirmed correctness bug in this scoped pass.

**Healthy Signals**
- `document_inventory` answers now bypass web search, embeddings, retrieval, and LLM generation for deterministic workspace-state questions.
- Tests verify both positive inventory routing and negative domain-question routing.
- The change added no dependency, shell execution, unsafe deserialization, or external integration.

**Permanent Fixes**
- Extracted document-inventory answer construction to `backend/app/services/document_inventory.py`.
- Kept `RagService` responsible for orchestration only: classify, call document service, delegate response construction, and return `PreparedAnswer`.
- Narrowed app-help regexes so only app/workspace/document usage questions shortcut conversation.
- Added regression coverage for assistant meta-chat, document inventory, domain "how do I use..." near-miss behavior, and document-inventory trace semantics.

**Validation**
- `D:\projects\chat\backend\.venv\Scripts\python.exe C:\Users\SAI\.codex\skills\audit-ai-slop\scripts\graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`
  - Result: whole-repo graph-only triage `26/100` low, whole-repo graph-plus-source triage `86/100` severe; used as triage only for this scoped source inspection.
- `D:\projects\chat\backend\.venv\Scripts\python.exe -m pytest tests\test_chat_intent_and_reasoning.py tests\test_rag_grounding.py` in `backend/`
  - Result: `16 passed`.
- `D:\projects\chat\backend\.venv\Scripts\python.exe -m py_compile app\services\message_intent.py app\services\rag_service.py app\services\answer_trace.py app\services\document_inventory.py` in `backend/`
  - Result: passed.
- `git diff --check -- backend\app\services\message_intent.py backend\app\services\rag_service.py backend\app\services\answer_trace.py backend\app\services\document_inventory.py backend\tests\test_chat_intent_and_reasoning.py`
  - Result: no whitespace errors; Git emitted existing LF-to-CRLF warnings only.

Residual risk:
- Live Render/Netlify deployments were not updated in this audit pass. The code path is fixed locally and needs redeploy for the portfolio site.

---

## Chat Rate Limit And Web Search Audit Pass - 2026-06-12

**Verdict**
Score: 22/100, Low slop risk after repair
Confidence: Medium

Scope: chat abuse-control and web-search reliability edits made in this prompt plus directly connected architecture: `backend/app/services/chat_rate_limiter.py`, `backend/app/services/web_search_service.py`, `backend/app/routers/chat.py`, `backend/app/core/config.py`, `backend/app/services/container.py`, `backend/tests/test_chat_rate_limiter.py`, `backend/tests/test_web_search_service.py`, `backend/tests/test_config.py`, and the web-search regression in `backend/tests/test_chat_intent_and_reasoning.py`.

Graphify freshness: `graphify-out/GRAPH_REPORT.md` dated 2026-05-17.

Important context: the bundled Graphify triage scanner again reported whole-repo graph-only triage `26/100` and graph-plus-source triage `86/100`. This section scores only the prompt-touched chat-rate-limit and web-search path after source inspection and repair.

**Why**
- Graphify identifies `RagService`, `ServiceContainer`, and `query_chat()`/`stream_chat()` as central chat-path nodes, so abuse controls and web-search failure handling belong at stable boundaries instead of frontend-only UI state.
- The chat endpoints had no per-user/per-client request budget before history, retrieval, web search, or model calls.
- Live provider smoke testing confirmed DuckDuckGo returned usable raw results, but `WebSearchService._hydrate_results()` discarded all results when target page fetches failed.
- The repaired path adds strict backend rate limiting, preserves clear container boundaries, and treats provider snippets as valid fallback web evidence when full-page hydration fails.

**Evidence**
| Signal | Graph Evidence | Source Evidence | Classification | Likely Root Cause | Permanent Fix | Prevention Gate |
|---|---|---|---|---|---|---|
| Public chat endpoints could trigger expensive work without an abuse budget | `query_chat()` and `stream_chat()` are in Community 21; `ServiceContainer` is god node #10 with 24 edges | Limiter now gates chat before topic/history/retrieval at `backend/app/routers/chat.py:100` and `backend/app/routers/chat.py:237`; policy lives in `backend/app/services/chat_rate_limiter.py:20` | Confirmed slop signal, fixed | Demo deployment focused on functionality before adding resource-governance controls | Added strict sliding-window limits per user and per client IP, returning `429` plus `Retry-After` | Any public AI endpoint must have backend-side resource limits before invoking retrieval, search, or model calls |
| Web search failed when full target-page hydration was unavailable | Community 18 is the web-search integration cluster; `RagService` is god node #5 and depends on this evidence path | `backend/app/services/web_search_service.py:157` now keeps search-result snippets via `backend/app/services/web_search_service.py:179`; live smoke test returned 3 results after repair | Confirmed slop signal, fixed | Search integration treated page hydration as mandatory even though provider snippets were already usable evidence | Added snippet fallback results while preserving full-page content when available | Web integrations must degrade to provider metadata/snippets instead of collapsing to unavailable when secondary enrichment fails |
| Rate-limit configuration needed deployment tuning without code edits | Community 5 contains `Settings` and `load_settings()` as central config infrastructure | Defaults and env overrides are in `backend/app/core/config.py:45`, `backend/app/core/config.py:159`, and tested at `backend/tests/test_config.py:41` | Healthy architecture signal | Strict demo limits need operational tuning across local/deployed environments | Added `RAG_CHAT_RATE_LIMIT_PER_MINUTE` and `RAG_CHAT_RATE_LIMIT_PER_HOUR` with strict defaults of `3` and `12` | Keep operational limits configurable, but safe by default |
| Web-search toggle needed backend-path regression coverage | `RagService` bridges retrieval, web, and intent communities | `backend/tests/test_chat_intent_and_reasoning.py:329` proves web search is called when PDF context is empty and the toggle is enabled | Healthy verification signal | UI toggle behavior can regress silently if only provider tests exist | Added a RAG-level regression that checks the web-search call, tool call, and web evidence context | Tests for toggles should verify backend effects, not only frontend state |

**Aggressive Review Targets**
- The in-memory limiter is correct for the current single-instance Render demo, but a multi-instance deployment would need Redis/Upstash or edge rate limiting to share counters.
- The whole-repo scanner still flags broad error masking in `backend/app/routers/chat.py` and `backend/app/services/rag_service.py`; those are outside this scoped pass except where the new limiter/web-search code touches them.

**Healthy Signals**
- No new dependencies, shell execution, unsafe deserialization, or hidden dashboard-only configuration were added.
- The rate limiter has deterministic tests for per-minute, per-hour, per-user, per-client, expiry, forwarded IP extraction, and `429` response behavior.
- The web-search fix was verified with unit tests and a live provider smoke test.

**Permanent Fixes**
- Added `ChatRateLimiter` as a focused service instead of spreading counters through route handlers or frontend state.
- Wired the limiter into both `/api/chat/query` and `/api/chat/stream` before expensive chat work.
- Added strict default limits: 3 messages/minute and 12 messages/hour, with deployment env overrides.
- Repaired `WebSearchService` so failed full-page hydration falls back to provider snippets rather than discarding usable search results.
- Added regression tests for limiter behavior, config defaults/overrides, snippet fallback, and RAG web-search usage.

**Anti-Slop Gates**
- Any public model-backed route should have a backend resource budget and a test that proves exhaustion returns a typed response.
- Any external enrichment step should preserve lower-fidelity but valid upstream evidence when optional hydration fails.
- Keep frontend toggles paired with backend-path tests so UI state cannot imply behavior the backend does not execute.

**Validation**
- `D:\projects\chat\backend\.venv\Scripts\python.exe C:\Users\SAI\.codex\skills\audit-ai-slop\scripts\graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`
  - Result: whole-repo graph-only triage `26/100`; whole-repo graph-plus-source triage `86/100`; used as triage only for this scoped audit.
- `D:\projects\chat\backend\.venv\Scripts\python.exe -m pytest tests\test_chat_rate_limiter.py tests\test_web_search_service.py tests\test_config.py tests\test_chat_intent_and_reasoning.py tests\test_rag_grounding.py tests\test_rag_retrieval.py`
  - Result: `35 passed`.
- `D:\projects\chat\backend\.venv\Scripts\python.exe -m py_compile app\services\chat_rate_limiter.py app\services\web_search_service.py app\routers\chat.py app\services\container.py app\core\config.py app\services\rag_service.py`
  - Result: passed.
- `git diff --check -- backend\app\services\chat_rate_limiter.py backend\app\services\web_search_service.py backend\app\routers\chat.py backend\app\services\container.py backend\app\core\config.py backend\tests\test_chat_rate_limiter.py backend\tests\test_web_search_service.py backend\tests\test_config.py backend\tests\test_chat_intent_and_reasoning.py`
  - Result: no whitespace errors; Git emitted existing LF-to-CRLF warnings only.
- Live local smoke test using `WebSearchService.search("OpenAI latest news")`
  - Result: returned 3 web results after snippet fallback repair.

Residual risk:
- These fixes are local only until the backend is redeployed to Render. The currently hosted portfolio site will not enforce the new limits or use the repaired web-search fallback until deployment completes.

### Stop-Hook Re-Audit Confirmation - 2026-06-12

Scope: same prompt-touched chat rate-limit and web-search path as above, plus directly connected route/config/container/test code.

Result: no additional confirmed slop-like defect was found after re-reading the audit skill, Graphify report, scanner output, and scoped source files. The prior fixes remain the root-cause repair: backend-side chat budgeting before expensive AI work, snippet fallback for web-search hydration failures, strict config defaults, and behavior-level tests.

Validation refreshed in this pass:
- `D:\projects\chat\backend\.venv\Scripts\python.exe C:\Users\SAI\.codex\skills\audit-ai-slop\scripts\graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`
  - Result: whole-repo graph-only triage `26/100`; whole-repo graph-plus-source triage `86/100`; used as triage only for this scoped audit.
- Scoped source inspection:
  - Result: no new over-indirection, fake integration, weakened test, unsafe sink, or missing validation was found in the newly added rate-limit/web-search code.
