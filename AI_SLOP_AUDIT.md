**Verdict**
Score: 25/100, Low slop risk
Confidence: Medium-high

**Final Rating**
25/100. This is low slop risk, not minimal slop. The biggest confirmed slop-like risks have been reduced, but the repository still has source-backed architecture pressure that keeps it above the 0-20 minimal range.

**Can this honestly be <5/100?**
No. A sub-5 score would be dishonest while the repo still has verified architecture pressure in document persistence, ingestion/topic cross-store consistency, and large frontend orchestration components. The graph-only triage is `19/100`; the source-augmented scanner reports `64/100`, but that higher number includes docs, mockups, package-lock entries, ignored temp/vendor material, and audit-report text. Final scoring below is source-verified, not vibe-based.

**Scope**
- Repository root: `D:/projects/chat`
- Branch audited: `main`
- Audit date: 2026-05-15
- Graphify was read before source inspection. The current report is dated 2026-05-15 and was regenerated after the retrieval-policy and ingestion-parser splits.
- Final rating pass ran on 2026-05-15 after commit `15433be`; the later ingestion-parser split is recorded in this report.
- Sub-agents were used as bounded read-only verifiers for RAG, backend god nodes, frontend architecture, and repo hygiene. Their findings are integrated here.

**Why**
- `RagService` was a confirmed god-object risk before this pass: it owned answer orchestration plus retrieval, comparison retrieval, web reranking, and local context checks.
- That RAG risk was reduced permanently by introducing `RagRetrievalEngine` as a real retrieval/search boundary, then moving deterministic retrieval policy out of that engine so it does not become a replacement god object.
- Two tracked one-off rewrite scripts, `patchTSX.js` and `splitCSS.js`, were stale refactor residue and were removed.
- Larger confirmed risks remain outside this pass: `DocumentService` spans persistence/vector/preview concerns, ingestion and topic indexing still need a durable unit-of-work, and frontend workbench/KG explorer components still aggregate multiple domains.
- Security scans found no tracked secret and `npm audit --omit=dev --audit-level=moderate` reports `0 vulnerabilities`; the PDF HTML path remains governed but security-sensitive.

**Evidence**
| Signal | Graph Evidence | Source Evidence | Classification | Impact |
|---|---|---|---|---|
| RAG god-object split | Fresh Graphify: `RagService` 71 edges, `RagRetrievalEngine` 43 edges; betweenness for `RagService` now reflects coordination plus model/generation dependencies. | `backend/app/services/rag_service.py` is now 801 lines; retrieval/search/rerank behavior moved to `backend/app/services/rag_retrieval.py`; `backend/tests/test_rag_retrieval.py` covers direct lexical shortcut and scoped collection retrieval. | Confirmed slop signal, fixed | RAG retrieval no longer lives inside the answer-generation service. |
| Retrieval policy boundary | Fresh Graphify still reports `RagRetrievalEngine` as a top connected node after the service split. | `backend/app/services/rag_retrieval_policy.py` now owns FTS query construction, RRF scoring, flat-collection fallback policy, rerank pool sizing, comparison coverage selection, and rerank-decision rules; `backend/tests/test_rag_retrieval_policy.py` covers those policies without Chroma/KG/reranker fakes. | Confirmed slop signal, fixed | The retrieval engine now orchestrates stores and delegates deterministic policy instead of accumulating hidden ranking rules. |
| RAG helper boundary | Helper communities still exist for answer text, citations, grounding, comparison, and prompting. | `backend/app/services/rag_answer_text.py` now owns `first_sentence`, `is_informative_answer_sentence`, and `comparison_sentence_for_context`; `RagService` consumes helpers directly. | Healthy architecture signal | Prevents helper logic from drifting back into service-private methods. |
| Multi-store document service | Graphify still reports `DocumentService` as a god node with 42 edges. | `backend/app/services/document_service.py` is 927 lines and owns DB records, Chroma chunks, FTS catalog sync, corpus versioning, and preview HTML rendering. | Confirmed architecture risk | Needs repository/storage boundary split before whole-repo score can be minimal. |
| Ingestion parser/chunking boundary | Graphify now places `ParsedBlock`, `ParsedDocument`, `ParsedPage`, `DocumentParser`, `DoclingDocumentParser`, and `IngestionChunkBuilder` in their own parser/chunking community. | `IngestionService` now depends on `DocumentParser`; Docling remains the concrete implementation. `IngestionChunkBuilder` owns QA/page chunk drafting, and focused tests cover the split. | Confirmed slop signal, fixed | Ingestion no longer owns parser-specific chunk policy or a concrete Docling type. |
| Ingestion cross-store lifecycle | `IngestionService` remains a top connected node. | Ingestion still writes Chroma chunks, retrieval catalog records, pages, topic metadata, and document status through separate operations, with broad cleanup on failure. | Confirmed architecture risk | Partial external state can exist unless the lifecycle is made durable and reconciliable. |
| Topic/KG consistency | `TopicIndexService`, `KgManager`, and `ChromaStore` remain connected through inferred and source-confirmed relationships. | Topic indexing mutates Chroma metadata, SQLite catalog state, and KG JSON without one transaction boundary. | Confirmed consistency risk | Topic state can diverge across stores after partial failure. |
| Frontend workbench provider | Graphify community 15 still centers on `WorkbenchProvider`. | `frontend/src/app/providers/workbench/WorkbenchProvider.tsx` is 884 lines and still owns sessions, streaming chat, ingestion events, preview state, uploads, reclustering, viewport state, and toasts. | Confirmed frontend architecture risk | Needs domain-sliced providers/hooks or reducer slices. |
| Knowledge graph explorer | Frontend graph/model code is partially extracted, but explorer remains central. | `frontend/src/widgets/knowledge-graph-explorer/KnowledgeGraphExplorer.tsx` is 841 lines and mixes layout simulation, camera/export, URL sync, toolbar, inspector, and accessibility behavior. | Confirmed maintainability risk | Needs layout/camera/canvas/inspector splits before minimal-risk scoring. |
| PDF preview HTML sink | Scanner flags `dangerouslySetInnerHTML`. | Frontend injects backend preview HTML; backend escapes document text before inserting controlled highlight spans. Existing markdown tests also assert raw HTML escaping for assistant output. | Benign but governed | Keep as security-sensitive review target; structured preview blocks would be stronger. |
| Tracked one-off rewrite scripts | Source scan found file-write tooling in root. | `patchTSX.js` and `splitCSS.js` were tracked, unreferenced scripts that rewrote source files. | Confirmed repo hygiene slop, fixed | Removed obsolete mutation scripts from tracked source. |

**Score Breakdown**
- Graph structure: 8/25. Graph-only triage is minimal at `19/100`, but centrality remains concentrated in RAG, document, topic, and history services.
- Architectural integrity: 7/25. RAG and ingestion parsing boundaries are much healthier; document/topic lifecycle and frontend provider boundaries still carry real coupling.
- Maintainability and code smells: 4/20. The worst stale scripts are gone and ingestion shed chunk policy; several 650-900 line orchestration files remain.
- Verification and test quality: 3/15. Backend tests are meaningful and green, including focused ingestion chunking tests, but integration/failure-path coverage is still thin around multi-store lifecycles and frontend interaction flows.
- Security and configuration hygiene: 2/10. No tracked secrets were confirmed and `npm audit` previously passed; the governed PDF HTML sink stays security-sensitive.
- Documentation/provenance honesty: 1/5. Audit/docs now accurately call out remaining risk; some older planning/mockup docs still create scanner noise.

**Aggressive Review Targets**
- Split `DocumentService` into document repository, chunk catalog repository, vector chunk store, and preview rendering service.
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
- Moved reusable answer sentence helpers into `backend/app/services/rag_answer_text.py`.
- Deleted stale tracked refactor scripts `patchTSX.js` and `splitCSS.js`.
- Regenerated Graphify after the code changes.

**Validation**
- `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`: completed after the ingestion split; graph-only `19/100`, source-augmented triage `64/100` across 185 source-like files. The high source score still includes known docs/mockup/ignored-temp/lockfile/audit-report noise.
- `python -m graphify update .`: passed after retrieval fixes; command output rebuilt `1061 nodes`, `2070 edges`, `55 communities`; `GRAPH_REPORT.md` summary reported `1061 nodes`, `2070 edges`, `33 communities detected`.
- `backend/.venv/Scripts/python -m compileall backend/app/services/rag_retrieval.py backend/app/services/rag_retrieval_policy.py backend/tests/test_rag_retrieval.py backend/tests/test_rag_retrieval_policy.py`: passed.
- `$env:PYTHONPATH='backend'; backend/.venv/Scripts/python -m pytest backend/tests/test_rag_retrieval.py backend/tests/test_rag_retrieval_policy.py`: passed, `9 passed`.
- `$env:PYTHONPATH='backend'; backend/.venv/Scripts/python -m pytest backend/tests`: passed, `39 passed`.
- `$env:PYTHONPATH='backend'; backend/.venv/Scripts/python -m pytest backend/tests/test_docling_parser.py backend/tests/test_ingestion_docling_contract.py backend/tests/test_ingestion_chunk_builder.py`: passed, `8 passed`.
- `$env:PYTHONPATH='backend'; backend/.venv/Scripts/python -m pytest backend/tests`: passed after the ingestion split, `42 passed`.
- `python -m graphify update .`: passed after the ingestion split; command output rebuilt `1094 nodes`, `2175 edges`, `50 communities`; `GRAPH_REPORT.md` summary reports `1094 nodes`, `2175 edges`, `28 communities detected`.
- Previous frontend validation remains unchanged because the retrieval and ingestion splits touched backend code only: `frontend/npm run typecheck`, `frontend/npm run test:message-markdown`, `frontend/npx tsx --test tests/knowledge-graph-model.test.ts`, `frontend/npx tsx --test src/app/providers/workbench/workbenchStateHelpers.test.ts`, `frontend/npm run build`, and `frontend/npm audit --omit=dev --audit-level=moderate` all passed in the prior audit/fix pass.
- Source corroboration after the ingestion split inspected the current Graphify god nodes, line counts, tracked/ignored scanner-noise sources, and code smell buckets. The remaining confirmed issues are larger architecture work already listed as review targets.
- `git diff --check`: passed, with only Git line-ending conversion warnings.

**Residual Risk**
- Whole-repo slop risk is low, not minimal. The remaining issues are real architecture work, not scanner noise.
- The latest prompt-scope slop signal was fixed by the ingestion parser/chunking split. I did not start another audit/fix loop from the audit-report-only changes.
