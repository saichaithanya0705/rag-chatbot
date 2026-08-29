# Local RAG Chatbot Workspace

This repository contains a full local RAG chatbot application with:

- a TypeScript React frontend that matches the provided mockup layout
- a FastAPI backend for chat, sessions, ingestion, preview, topics, and graph APIs
- a local-first retrieval pipeline built on ChromaDB, SQLite, FastEmbed, NVIDIA NIM, and Celery
- OpenDataLoader PDF parsing for digital text, layout, lists, and tables
- topic clustering, a directed knowledge graph, chat memory, and optional web fallback

The repository started from the phased plan in [rag_chatbot_phases.md](./rag_chatbot_phases.md) and the UI reference in [chatbot_ui_mockup.html](./chatbot_ui_mockup.html). The implementation now covers the full Phase 1-6 scope that was planned across those documents.

## What The App Does

At a high level, the app lets you:

- upload PDFs into a local knowledge base
- ask questions in a chat UI with streaming responses
- cite exact PDF passages and open them in a preview panel
- organize retrieval by topic collections
- visualize topic relationships in a knowledge graph
- persist chat sessions and retrieve memory from past conversations
- fall back to web search when the local corpus is not enough
- parse text, lists, tables, and layout from digital PDFs through OpenDataLoader

## Current Feature Set

### Chat

- persistent sessions with auto-generated titles
- grouped session list in the sidebar
- streaming assistant replies
- single-flight send protection while a model response is in progress
- safe rich-text message rendering for paragraphs, lists, headings, inline code, and fenced code blocks
- citation chips for PDF and web sources
- collection-scoped retrieval
- web-search toggle

### Retrieval And Ingestion

- OpenDataLoader PDF parsing for digital text, layout, lists, and tables
- repeated margin header/footer cleanup using OpenDataLoader block provenance
- semantic chunking
- LLM-first keyword and topic tag extraction with KeyBERT fallback
- vector retrieval + BM25 + reciprocal rank fusion + reranking
- query rewriting for follow-up questions
- per-topic Chroma collections
- topic reclustering
- directed knowledge graph edges
- worker-backed ingestion through Celery using a filesystem transport

### Memory

- SQLite-backed session/message persistence
- vectorized chat memory in a dedicated `chat_history` collection
- same-session retrieval memory
- cross-session memory support keyed by `x-user-id`

### Pipeline UI

- file list with chunk counts, topic chips, and overlap summaries
- upload flow with live status progression
- manual recluster action
- knowledge graph view
- PDF preview panel with highlighted cited text

## Architecture

### Frontend

The frontend is a route-based React app with a clear separation between app shell, page layer, widgets, and shared utilities:

- [App.tsx](./frontend/src/app/App.tsx)
- [router.tsx](./frontend/src/app/router.tsx)
- [WorkbenchProvider.tsx](./frontend/src/app/providers/workbench/WorkbenchProvider.tsx)
- [httpWorkbench.ts](./frontend/src/shared/api/httpWorkbench.ts)
- [types.ts](./frontend/src/shared/api/types.ts)

The main widget areas are:

- [chat-shell](./frontend/src/widgets/chat-shell)
- [pipeline-shell](./frontend/src/widgets/pipeline-shell)
- [pdf-viewer](./frontend/src/widgets/pdf-viewer)
- [workbench-frame](./frontend/src/widgets/workbench-frame)

### Backend

The backend is a FastAPI app with routers and service modules separated by responsibility:

- [main.py](./backend/app/main.py)
- [routers](./backend/app/routers)
- [services](./backend/app/services)
- [schemas.py](./backend/app/models/schemas.py)
- [config.py](./backend/app/core/config.py)
- [database.py](./backend/app/core/database.py)

Important service modules:

- [rag_service.py](./backend/app/services/rag_service.py)
- [ingestion_service.py](./backend/app/services/ingestion_service.py)
- [history_service.py](./backend/app/services/history_service.py)
- [topic_index_service.py](./backend/app/services/topic_index_service.py)
- [kg_manager.py](./backend/app/services/kg_manager.py)
- [opendataloader_parser.py](./backend/app/services/opendataloader_parser.py)
- [query_rewrite_service.py](./backend/app/services/query_rewrite_service.py)
- [web_search_service.py](./backend/app/services/web_search_service.py)

## Storage Model

The app stores data locally inside [backend/data](./backend/data):

- `app.db`: SQLite data for sessions, messages, ingested documents, and page text
- `chroma/`: ChromaDB vector store
- `kg.pkl`: persisted directed knowledge graph
- `uploads/`: uploaded PDF files
- `celery/`: filesystem transport directories for Celery

Primary storage responsibilities:

- SQLite holds session metadata, messages, PDF metadata, and page text
- ChromaDB holds chunk embeddings, topic collections, and chat memory embeddings
- NetworkX holds the directed topic graph and is serialized to `kg.pkl`

## Repository Layout

```text
chat/
|-- backend/
|   |-- app/
|   |   |-- core/
|   |   |-- models/
|   |   |-- routers/
|   |   |-- services/
|   |   `-- tasks/
|   |-- data/
|   |-- scripts/
|   |-- requirements.txt
|   `-- README.md
|-- frontend/
|   |-- src/
|   |   |-- app/
|   |   |-- pages/
|   |   |-- shared/
|   |   `-- widgets/
|   |-- scripts/
|   `-- package.json
|-- chatbot_ui_mockup.html
|-- rag_chatbot_plan.md
`-- rag_chatbot_phases.md
```

## Prerequisites

This project has been verified on Windows with:

- Python `3.11.9`
- Node.js with `npm`
- OpenJDK 17 available on `PATH` for OpenDataLoader

Recommended local prerequisites:

- Python `3.11.x`
- Node.js `20+`
- OpenJDK 17 installed and available on `PATH`
- enough RAM/disk for FastEmbed model caching and ChromaDB

## Models

The backend defaults are currently:

- local embedding model: `BAAI/bge-small-en-v1.5` through FastEmbed (384 dimensions)
- NVIDIA chat model: `meta/llama-3.2-11b-vision-instruct`

Set `RAG_NVIDIA_API_KEY` for chat generation. You can verify configured model access with:

```powershell
cd D:\projects\chat\backend
.venv\Scripts\python scripts\verify_models.py
```

## Quick Start

### 1. Backend Setup

```powershell
cd D:\projects\chat\backend
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
```

### 2. Frontend Setup

```powershell
cd D:\projects\chat\frontend
npm install
```

### 3. Start The Celery Worker

The Celery worker is the **background ingestion engine**. It must be running whenever you want to upload and index new PDFs. Without it, uploaded files will stay stuck at "Queued" indefinitely.

The worker handles the full document processing pipeline:

1. **Parsing** — Converts digital PDFs through OpenDataLoader core with text, layout, list, and table extraction
2. **Source mapping** — Stores OpenDataLoader labels, block refs, bounding boxes, and source text for preview/highlighting
3. **Chunking** — Splits extracted text into overlapping semantic chunks
4. **Embedding** — Generates vector embeddings through NVIDIA NIM or the resolved local FastEmbed model and stores them in ChromaDB
5. **Topic extraction** — Uses the LLM (with KeyBERT fallback) to generate topic tags
6. **Clustering** — Assigns documents to topic collections
7. **Knowledge graph** — Builds directed edges between related topics

This runs as a separate process so the API server stays responsive during heavy ingestion. No Redis or RabbitMQ is required — the project uses a local filesystem transport.

> **Note:** If you only need to chat with already-indexed documents, the worker is not required. But any new uploads will not be processed without it.

```powershell
cd D:\projects\chat\backend
.venv\Scripts\python scripts\run_celery_worker.py
```

### 4. Start The API

Default local run:

```powershell
cd D:\projects\chat\backend
.venv\Scripts\python -m uvicorn app.main:app --app-dir D:\projects\chat\backend --host 127.0.0.1 --port 8000
```

### 5. Start The Frontend

If the backend is on the default `8000` port:

```powershell
cd D:\projects\chat\frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

If you want to run against a custom backend port, set `VITE_API_BASE_URL` first:

```powershell
cd D:\projects\chat\frontend
$env:VITE_API_BASE_URL = "http://127.0.0.1:8002"
npm run dev -- --host 127.0.0.1 --port 4177
```

Then open:

- [http://127.0.0.1:5173/chat](http://127.0.0.1:5173/chat) for the default setup
- or the custom frontend URL you started

## Production Build

Frontend production build:

```powershell
cd D:\projects\chat\frontend
npm run build
```

The frontend build also generates static route entrypoints for direct navigation:

- `dist/chat/index.html`
- `dist/pipeline/index.html`
- `dist/404.html`

That route generation is handled by [generate-static-routes.mjs](./frontend/scripts/generate-static-routes.mjs).

Backend sanity check:

```powershell
cd D:\projects\chat\backend
.venv\Scripts\python -m compileall app scripts
```

## API Overview

Base prefix: `/api`

### System

- `GET /api/system/health`

### Sessions

- `GET /api/sessions`
- `POST /api/sessions`
- `GET /api/sessions/{session_id}`
- `DELETE /api/sessions/{session_id}`

### Chat

- `POST /api/chat/query`
- `POST /api/chat/stream`

### Documents

- `GET /api/documents`
- `POST /api/documents/upload`
- `DELETE /api/documents/{document_id}`
- `GET /api/documents/preview`

### Topics And Graph

- `GET /api/topics`
- `POST /api/topics/recluster`
- `GET /api/topics/graph`
- `GET /api/kg/graph`

## Scripts

Useful backend scripts in [backend/scripts](./backend/scripts):

- [verify_models.py](./backend/scripts/verify_models.py): checks configured embeddings and NVIDIA chat generation
- [run_celery_worker.py](./backend/scripts/run_celery_worker.py): starts the ingestion worker
- [ingest_pdf.py](./backend/scripts/ingest_pdf.py): one-off ingest script
- [generate_sample_pdf.py](./backend/scripts/generate_sample_pdf.py): generates a small sample PDF fixture
- [generate_scanned_test_pdf.py](./backend/scripts/generate_scanned_test_pdf.py): generates an image-only fixture for verifying the explicit unsupported-OCR error path

## Environment Variables

The main backend configuration lives in [config.py](./backend/app/core/config.py).

Common environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `RAG_NVIDIA_BASE_URL` | NVIDIA NIM API base URL | `https://integrate.api.nvidia.com/v1` |
| `RAG_NVIDIA_API_KEY` | NVIDIA NIM API key used for chat and cloud models | unset |
| `RAG_EMBED_MODEL` | cloud or local embedding model | `BAAI/bge-small-en-v1.5` |
| `RAG_EMBEDDING_DIMENSIONS` | expected embedding vector length | `384` |
| `RAG_NVIDIA_CHAT_MODEL` | NVIDIA chat model | `meta/llama-3.2-11b-vision-instruct` |
| `RAG_RERANKER_MODEL` | NVIDIA reranker model | `nvidia/nv-rerankqa-mistral-4b-v3` |
| `RAG_ENABLE_CROSS_SESSION_MEMORY` | enable cross-session memory | `true` |
| `RAG_DATA_DIR` | persistent SQLite, Chroma, graph, upload, and queue root | `backend/data` |
| `RAG_WEB_SEARCH_BACKEND` | search backend | `duckduckgo` |
| `RAG_WEB_SEARCH_REGION` | search region | `us-en` |
| `RAG_WEB_SEARCH_MAX_RESULTS` | max web results | `4` |
| `RAG_WEB_SEARCH_SCORE_THRESHOLD` | fallback threshold | `0.3` |
| `RAG_ALLOWED_ORIGINS` | explicit CORS origins | local defaults |
| `RAG_ALLOWED_ORIGIN_REGEX` | regex CORS matcher | local host/port regex |
| `RAG_CELERY_QUEUE` | ingestion queue name | `rag_ingestion` |

Frontend environment variable:

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | backend base URL for the frontend |

## Request Context And User Identity

The backend reads `x-user-id` from request headers in [dependencies.py](./backend/app/dependencies.py).

The frontend generates and stores a stable local user id automatically in browser storage, which is used to:

- separate session lists
- separate chat memory
- support cross-session memory per local user

## Notes On OpenDataLoader Parsing

OpenDataLoader core is the document parser used by ingestion. The Docker image includes the small Java 17 runtime it requires.

Current parsing path:

- ingestion converts PDFs with `opendataloader_pdf.convert`
- structured text blocks, headings, lists, tables, page coordinates, and source references are normalized before chunking
- repeated marginal headers/footers are removed from parser blocks before chunking
- chunk metadata stores parser name, content labels, table flags, source refs, source text, and source block boxes

Important capability boundary:

- this small-runtime build intentionally uses OpenDataLoader core and does not include the hybrid OCR service
- image-only/scanned PDFs fail with an explicit OCR-required message instead of being indexed as empty documents
- `pypdfium2` is a digital-text fallback if OpenDataLoader conversion fails

## Design And UI Notes

The UI implementation was built to preserve the supplied mockup layout:

- the structural reference is [chatbot_ui_mockup.html](./chatbot_ui_mockup.html)
- the React shell lives in [workbench-frame](./frontend/src/widgets/workbench-frame)
- routes are limited to `/chat` and `/pipeline`

The frontend intentionally separates:

- data access
- application state
- page-level composition
- reusable visual widgets

## Known Characteristics

These are not necessarily bugs, but they are good to know:

- topic labels are auto-generated from clustering and may look a little awkward on very small corpora
- OpenDataLoader starts a Java conversion process during PDF ingestion
- image-only PDFs require a separately deployed OCR service and are intentionally unsupported by this image
- if you run frontend and backend on non-default ports, set `VITE_API_BASE_URL` explicitly

## Troubleshooting

### Frontend Says `Failed to fetch`

Usually one of these is true:

- the backend is not running
- the frontend is pointing at the wrong API base URL
- you started the backend on a non-default port but did not set `VITE_API_BASE_URL`

Check:

```powershell
curl http://127.0.0.1:8000/api/system/health
```

Or for a custom port:

```powershell
curl http://127.0.0.1:8002/api/system/health
```

### Direct Route Open Returns 404

Use the production build output generated by `npm run build`, which writes:

- `dist/chat/index.html`
- `dist/pipeline/index.html`
- `dist/404.html`

This is required for direct-open static hosting of `/chat` and `/pipeline`.

### CORS Problems On Localhost Or 127.0.0.1

The backend already accepts local development origins by default, including arbitrary local ports through the configured regex. If you override CORS settings manually, make sure both:

- `localhost`
- `127.0.0.1`

are still covered.

### OpenDataLoader Parsing Fails

Check:

- `opendataloader-pdf` is installed from `backend/requirements.txt`
- Python version is `3.11.x` and `java -version` reports Java 17
- the PDF has a digital text layer; scanned/image-only PDFs need a separate OCR pipeline

### Duplicate Worker Or Server Processes

This project uses long-running local processes. If you restart things repeatedly during development, check for stale processes before starting new ones.

Typical processes to watch:

- `python.exe` for `uvicorn`
- `python.exe` for `run_celery_worker.py`
- `node.exe` for Vite

## References

- phased build reference: [rag_chatbot_phases.md](./rag_chatbot_phases.md)
- technical plan: [rag_chatbot_plan.md](./rag_chatbot_plan.md)
- UI source reference: [chatbot_ui_mockup.html](./chatbot_ui_mockup.html)
