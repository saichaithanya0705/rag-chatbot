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

Residual risk:
- Hosted Render/Netlify verification remains pending until the latest startup fixes are redeployed and exercised against the live URLs.
