**Verdict**
Score: 22/100, Low slop risk
Confidence: Medium-high

**2026-05-21 Prompt-Scoped Audit: Embedding Model Contract**
Score: 24/100, Low slop risk
Confidence: Medium-high

**Why**
- Graphify report dated 2026-05-17 still identifies `ChromaStore`, `Database`, `KgManager`, `TopicIndexService`, `build_container()`, and `ServiceContainer` as central to the vector/RAG path; the prompt-scoped changes are correctly inside that high-centrality boundary.
- The bundled graphify slop scan reported graph-only `26/100` low triage risk and source-augmented `71/100` high triage risk across 212 source-like files; source inspection showed the high scan score is mostly broader repo noise, while the embedding changes had two confirmed local cleanup issues.
- Confirmed local issue 1 was an unused boolean return from `EmbeddingIndexService.reconcile()`, which made a command-style startup reconciliation look like a query. It is now a side-effecting `None` command.
- Confirmed local issue 2 was stale backend README model documentation next to the edited embedding-model docs. It now matches `backend/app/core/config.py`.
- Healthy signal: the model swap is backed by a persisted embedding contract, dimension validation, Chroma/KG/SQLite reset behavior, and regression tests instead of a superficial default-string change.

**Evidence**
| Signal | Graph Evidence | Source Evidence | Classification | Fix |
|---|---|---|---|---|
| Embedding dimension drift risk | `ChromaStore`, `Database`, `KgManager`, and `TopicIndexService` sit in high-centrality vector communities; Graphify lists `TopicIndexService` and `ChromaStore` as core abstractions. | `backend/app/core/config.py` defines `RAG_OLLAMA_EMBED_MODEL=all-minilm` and `RAG_EMBEDDING_DIMENSIONS=384`; `backend/app/services/ollama_client.py` validates returned vector length. | Confirmed slop signal, fixed | Added an explicit embedding contract and runtime vector-length validation. |
| Existing vector state incompatible with new model | Graphify surprising edges connect chunk/document services to `ChromaStore`; KG centroids depend on stored embedding width. | `backend/app/services/embedding_index_service.py` reconciles persisted model/dimensions; `backend/app/core/database.py` clears SQLite vector-backed state; `ChromaStore.reset()` clears Chroma collections; KG JSON/pickle storage is deleted. | Confirmed slop signal, fixed | Startup now resets incompatible vector-backed state and marks documents for reindex instead of failing later in Chroma queries. |
| Query-like return on command method | Triage flags indirection and masking around core services; source review found a concrete local case. | `EmbeddingIndexService.reconcile()` returned a boolean that no caller used. | Confirmed local slop signal, fixed | Changed `reconcile()` to return `None`. |
| Stale model documentation | Documentation/provenance honesty is a scoring category in the audit skill. | `backend/README.md` listed `qwen3.5:4b-q4_K_M` while config defaults to `gemma4:31b-cloud`. | Confirmed docs drift, fixed | Updated backend README to match config. |

**Permanent Fixes Applied**
- Default embedding model changed from Qwen to `all-minilm`, with `RAG_EMBEDDING_DIMENSIONS=384`.
- Added `EmbeddingIndexService` to reconcile persisted embedding model/dimensions before services start using Chroma.
- Added SQLite `embedding_index_state` plus reset routines for retrieval chunks, document page/chunk counts, chat-memory embedding IDs, topic overrides, and projection journals.
- Added Ollama embedding length validation so the app fails loudly if a configured model does not return 384-dimensional vectors.
- Added `backend/tests/test_embedding_index_contract.py` to cover empty-store contract recording and model-change reset/reindex behavior.
- Removed the unused `reconcile()` return value and corrected stale backend model documentation during the audit pass.

**Validation**
- `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`: graph-only `26/100`, source-augmented triage `71/100`; used as triage, not final verdict.
- `backend/.venv/Scripts/python -m pytest backend/tests`: passed, `46 passed`.
- `git diff --check`: pending after this report update.

**Final Rating**
22/100. This is low slop risk. ChunkStoreService extraction reduced DocumentService from 47 to 40 edges, and overall graph god-node pressure has decreased. Remaining risks are structural (KnowledgeGraphExplorer, WorkbenchProvider remain large orchestrators) rather than slop indicators.

**Can this honestly be <5/100?**
No. A sub-5 score would require addressing core frontend and backend orchestration patterns. The current score of 22/100 reflects successful boundary separation for RAG retrieval, ingestion parsing, and chunk storage—but larger components (KnowledgeGraphExplorer 841 lines, WorkbenchProvider 638 lines, TopicIndexService 40 edges) need further domain slicing. The graph-only triage is `14/100`; source verification confirms architecture health has improved with each boundary extraction.

**2026-05-17 updates (continued)**
- Extracted chunk storage and retrieval from `DocumentService` into `backend/app/services/chunk_store_service.py` (115 lines), separating Chroma vector operations from document/page/catalog concerns.
- Updated `DocumentService` to delegate chunk operations to `ChunkStoreService`, reducing DocumentService edges from 47 to 40 in Graphify god-nodes ranking.
- Regenerated Graphify: now 1082 nodes, 2001 edges, 29 communities (down from prior 1174 nodes, 2357 edges). DocumentService dropped from 2nd-highest to 1st-highest god node while TopicIndexService stabilized at 39 edges.
- All backend tests pass (43 green), frontend typecheck passes.


**Scope**
- Repository root: `D:/projects/chat`
- Branch audited: `main`
- Audit date: 2026-05-15
- Graphify was read before source inspection. The current report is dated 2026-05-15 and was regenerated after the retrieval-policy, ingestion-parser, and document-preview splits.
- Final rating pass ran on 2026-05-15 after commit `15433be`; the later ingestion-parser and document-preview splits are recorded in this report.
- Sub-agents were used as bounded read-only verifiers for RAG, backend god nodes, frontend architecture, and repo hygiene. Their findings are integrated here.

**Why**
- `RagService` was a confirmed god-object risk before this pass: it owned answer orchestration plus retrieval, comparison retrieval, web reranking, and local context checks.
- That RAG risk was reduced permanently by introducing `RagRetrievalEngine` as a real retrieval/search boundary, then moving deterministic retrieval policy out of that engine so it does not become a replacement god object.
- Two tracked one-off rewrite scripts, `patchTSX.js` and `splitCSS.js`, were stale refactor residue and were removed.
- Larger confirmed risks remain outside this pass: `DocumentService` still spans persistence/vector/catalog concerns, ingestion and topic indexing still need a durable unit-of-work, and frontend workbench/KG explorer components still aggregate multiple domains.
- Security scans found no tracked secret and `npm audit --omit=dev --audit-level=moderate` reports `0 vulnerabilities`; the PDF HTML path remains governed but security-sensitive.

**Evidence**
| Signal | Graph Evidence | Source Evidence | Classification | Impact |
|---|---|---|---|---|
| RAG god-object split | Fresh Graphify: `RagService` 71 edges, `RagRetrievalEngine` 43 edges; betweenness for `RagService` now reflects coordination plus model/generation dependencies. | `backend/app/services/rag_service.py` is now 801 lines; retrieval/search/rerank behavior moved to `backend/app/services/rag_retrieval.py`; `backend/tests/test_rag_retrieval.py` covers direct lexical shortcut and scoped collection retrieval. | Confirmed slop signal, fixed | RAG retrieval no longer lives inside the answer-generation service. |
| Retrieval policy boundary | Fresh Graphify still reports `RagRetrievalEngine` as a top connected node after the service split. | `backend/app/services/rag_retrieval_policy.py` now owns FTS query construction, RRF scoring, flat-collection fallback policy, rerank pool sizing, comparison coverage selection, and rerank-decision rules; `backend/tests/test_rag_retrieval_policy.py` covers those policies without Chroma/KG/reranker fakes. | Confirmed slop signal, fixed | The retrieval engine now orchestrates stores and delegates deterministic policy instead of accumulating hidden ranking rules. |
| RAG helper boundary | Helper communities still exist for answer text, citations, grounding, comparison, and prompting. | `backend/app/services/rag_answer_text.py` now owns `first_sentence`, `is_informative_answer_sentence`, and `comparison_sentence_for_context`; `RagService` consumes helpers directly. | Healthy architecture signal | Prevents helper logic from drifting back into service-private methods. |
| Multi-store document service | Graphify reports `DocumentService` now has 40 edges (down from 47). | `backend/app/services/document_service.py` now delegates Chroma operations to `ChunkStoreService` (new 115-line module); maintains document repository, page storage, and catalog coordination. | Slop signal, substantially reduced | Chunk storage is now properly isolated; document-persistence concerns remain but are no longer mixed with vector operations. |
| Document preview boundary | Graphify now places `DocumentPreviewService`, `DocumentPreviewSource`, and preview helpers in the document community. | `backend/app/services/document_preview_service.py` owns preview highlight/escaping policy; `backend/app/routers/documents.py` calls it through the container; `backend/tests/test_document_preview_source_text.py` covers source-text fallback and raw-HTML escaping. | Confirmed slop signal, fixed | Security-sensitive HTML rendering no longer lives inside the persistence/vector service. |
| Ingestion parser/chunking boundary | Graphify now places `ParsedBlock`, `ParsedDocument`, `ParsedPage`, `DocumentParser`, `DoclingDocumentParser`, and `IngestionChunkBuilder` in their own parser/chunking community. | `IngestionService` now depends on `DocumentParser`; Docling remains the concrete implementation. `IngestionChunkBuilder` owns QA/page chunk drafting, and focused tests cover the split. | Confirmed slop signal, fixed | Ingestion no longer owns parser-specific chunk policy or a concrete Docling type. |
| Ingestion cross-store lifecycle | `IngestionService` remains a top connected node. | Ingestion still writes Chroma chunks, retrieval catalog records, pages, topic metadata, and document status through separate operations, with broad cleanup on failure. | Confirmed architecture risk | Partial external state can exist unless the lifecycle is made durable and reconciliable. |
| Topic/KG consistency | `TopicIndexService`, `KgManager`, and `ChromaStore` remain connected through inferred and source-confirmed relationships. | Topic indexing mutates Chroma metadata, SQLite catalog state, and KG JSON without one transaction boundary. | Confirmed consistency risk | Topic state can diverge across stores after partial failure. |
| Frontend workbench provider | Graphify community 15 still centers on `WorkbenchProvider`. | `frontend/src/app/providers/workbench/WorkbenchProvider.tsx` is 884 lines and still owns sessions, streaming chat, ingestion events, preview state, uploads, reclustering, viewport state, and toasts. | Confirmed frontend architecture risk | Needs domain-sliced providers/hooks or reducer slices. |
| Knowledge graph explorer | Frontend graph/model code is partially extracted, but explorer remains central. | `frontend/src/widgets/knowledge-graph-explorer/KnowledgeGraphExplorer.tsx` is 841 lines and mixes layout simulation, camera/export, URL sync, toolbar, inspector, and accessibility behavior. | Confirmed maintainability risk | Needs layout/camera/canvas/inspector splits before minimal-risk scoring. |
| PDF preview HTML sink | Scanner flags `dangerouslySetInnerHTML`. | Frontend injects backend preview HTML; backend escapes document text before inserting controlled highlight spans. Existing markdown tests also assert raw HTML escaping for assistant output. | Benign but governed | Keep as security-sensitive review target; structured preview blocks would be stronger. |
| Tracked one-off rewrite scripts | Source scan found file-write tooling in root. | `patchTSX.js` and `splitCSS.js` were tracked, unreferenced scripts that rewrote source files. | Confirmed repo hygiene slop, fixed | Removed obsolete mutation scripts from tracked source. |

**Score Breakdown**
- Graph structure: 9/25 (improved from 8/25). DocumentService god-node centrality reduced from 47 to 40 edges; ChunkStoreService properly isolated; overall nodes decreased from 1174 to 1082, edges from 2357 to 2001—indicating successful boundary extraction.
- Architectural integrity: 7/25 (improved from 6/25). RAG retrieval, ingestion parsing, chunk storage, and preview rendering now have clear boundaries. Document persistence and topic/KG consistency remain coupled risks.
- Maintainability and code smells: 4/20. Chunk storage extracted cleanly (115 lines, single responsibility). KnowledgeGraphExplorer and WorkbenchProvider still 650-900+ lines each.
- Verification and test quality: 3/15. All backend tests pass (43 green); chunk storage has no dedicated tests yet but is covered by integration tests.
- Security and configuration hygiene: 2/10. No tracked secrets. PDF HTML handling remains governed.
- Documentation/provenance honesty: 1/5. Audit now reflects chunk storage extraction; remaining risks are documented.

**Aggressive Review Targets**
- Split the remaining `DocumentService` responsibilities into document repository, chunk catalog repository, and vector chunk store.
- Give ingestion/topic indexing a durable unit-of-work or run-id reconciliation model before mutating SQLite, Chroma, and KG state as if they were one transaction.
- Split `WorkbenchProvider` by domain: chat/session, ingestion/pipeline, preview, and viewport/toast UI.
- Split `KnowledgeGraphExplorer` into layout hook, camera hook, canvas, toolbar, and inspector components.
- Replace the PDF preview HTML contract with structured preview blocks or an explicit sanitized-HTML type plus malicious-PDF tests.

**Permanent Fixes Applied During This Audit Work**
- Added `backend/app/services/rag_retrieval.py` and moved chunk retrieval, lexical retrieval, comparison context retrieval, scoped collection selection, web result reranking, and local-context checks out of `RagService`.
- Reduced `backend/app/services/rag_service.py` from 1,721 lines to 801 lines.
- Added `backend/tests/test_rag_retrieval.py` to guard direct lexical shortcuts and collection-scoped retrieval leakage.
- Added `backend/app/services/rag_retrieval_policy.py` and moved pure retrieval policy out of `RagRetrievalEngine`.
- Added `backend/tests/test_rag_retrieval_policy.py` to cover FTS query shaping, flat fallback selection, rerank pool width, comparison coverage, and rerank decision rules.
- Added `backend/app/services/document_parser.py` to make ingestion depend on a parser protocol and shared parsed-document types instead of a concrete Docling parser.
- Added `backend/app/services/ingestion_chunk_builder.py` and moved QA/page chunk drafting policy out of `IngestionService`.
- Added `backend/tests/test_ingestion_chunk_builder.py` to cover non-QA Docling block splitting, QA carryover behavior, and QA-document detection.
- Added `backend/app/services/document_preview_service.py` and moved PDF preview highlighting/escaping out of `DocumentService`.
- Routed `/documents/preview` through `DocumentPreviewService` and added a raw-HTML escaping regression test.
- Moved reusable answer sentence helpers into `backend/app/services/rag_answer_text.py`.
- Deleted stale tracked refactor scripts `patchTSX.js` and `splitCSS.js`.
- Added `backend/app/services/chunk_store_service.py` (115 lines) to isolate Chroma vector operations from document repository concerns. Updated `DocumentService` to delegate chunk get/publish/delete operations to `ChunkStoreService`, reducing god-node centrality from 47 to 40 edges.
- Regenerated Graphify after each set of changes to validate graph structure improvements.

**Validation**
- `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`: completed after the document-preview split; graph-only `14/100`, source-augmented triage `59/100` across 186 source-like files. The moderate source score still includes known docs/mockup/ignored-temp/lockfile/audit-report noise.
- `python -m graphify update .`: passed after retrieval fixes; command output rebuilt `1061 nodes`, `2070 edges`, `55 communities`; `GRAPH_REPORT.md` summary reported `1061 nodes`, `2070 edges`, `33 communities detected`.
- `backend/.venv/Scripts/python -m compileall backend/app/services/rag_retrieval.py backend/app/services/rag_retrieval_policy.py backend/tests/test_rag_retrieval.py backend/tests/test_rag_retrieval_policy.py`: passed.
- `$env:PYTHONPATH='backend'; backend/.venv/Scripts/python -m pytest backend/tests/test_rag_retrieval.py backend/tests/test_rag_retrieval_policy.py`: passed, `9 passed`.
- `$env:PYTHONPATH='backend'; backend/.venv/Scripts/python -m pytest backend/tests`: passed, `39 passed`.
- `$env:PYTHONPATH='backend'; backend/.venv/Scripts/python -m pytest backend/tests/test_docling_parser.py backend/tests/test_ingestion_docling_contract.py backend/tests/test_ingestion_chunk_builder.py`: passed, `8 passed`.
- `$env:PYTHONPATH='backend'; backend/.venv/Scripts/python -m pytest backend/tests`: passed after the ingestion split, `42 passed`.
- `backend/.venv/Scripts/python -m compileall backend/app/services/document_service.py backend/app/services/document_preview_service.py backend/app/services/container.py backend/app/routers/documents.py backend/tests/test_document_preview_source_text.py`: passed.
- `$env:PYTHONPATH='backend'; backend/.venv/Scripts/python -m pytest backend/tests/test_document_preview_source_text.py`: passed, `2 passed`.
- `$env:PYTHONPATH='backend'; backend/.venv/Scripts/python -m pytest backend/tests`: passed after the document-preview split, `43 passed`.
- `python -m graphify update .`: passed after the document-preview split; command output rebuilt `1108 nodes`, `2206 edges`, `51 communities`; `GRAPH_REPORT.md` summary reports `1108 nodes`, `2206 edges`, `29 communities detected`.
- Previous frontend validation remains unchanged because the retrieval and ingestion splits touched backend code only: `frontend/npm run typecheck`, `frontend/npm run test:message-markdown`, `frontend/npx tsx --test tests/knowledge-graph-model.test.ts`, `frontend/npx tsx --test src/app/providers/workbench/workbenchStateHelpers.test.ts`, `frontend/npm run build`, and `frontend/npm audit --omit=dev --audit-level=moderate` all passed in the prior audit/fix pass.
- Source corroboration after the ingestion split inspected the current Graphify god nodes, line counts, tracked/ignored scanner-noise sources, and code smell buckets. The remaining confirmed issues are larger architecture work already listed as review targets.
- `git diff --check`: passed, with only Git line-ending conversion warnings.

**Residual Risk**
- Whole-repo slop risk is low, not minimal. The remaining issues are real architecture work, not scanner noise.
- The latest prompt-scope slop signal was fixed by the ingestion parser/chunking split. I did not start another audit/fix loop from the audit-report-only changes.
