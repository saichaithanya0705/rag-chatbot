# Local RAG Chat Backend

Backend for the local RAG chatbot. PDF ingestion uses OpenDataLoader core for digital text, layout, list/table reconstruction, and source-block metadata. This small runtime intentionally does not include OCR.

## Setup

```powershell
cd D:\projects\chat\backend
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes the pinned runtime requirements from `requirements.txt` plus the test runner.

## Run the API

```powershell
cd D:\projects\chat\backend
.venv\Scripts\python -m uvicorn app.main:app --reload
```

## Run tests

```powershell
cd D:\projects\chat\backend
.venv\Scripts\python -m pytest
```

## Ingest a PDF

```powershell
cd D:\projects\chat\backend
.venv\Scripts\python scripts\ingest_pdf.py "D:\path\to\notes.pdf"
```

OpenDataLoader requires Java 17 on `PATH`. Image-only PDFs fail with an explicit OCR-required message; add a separately deployed hybrid OCR service if scanned-document support becomes a requirement.

## Verify models

The backend defaults are:

- Local embedding model: `BAAI/bge-small-en-v1.5` through FastEmbed (384 dimensions)
- Chat model: `meta/llama-3.2-11b-vision-instruct` through NVIDIA NIM

You can override them with environment variables:

- `RAG_NVIDIA_BASE_URL`
- `RAG_NVIDIA_API_KEY`
- `RAG_EMBED_MODEL`
- `RAG_EMBEDDING_DIMENSIONS`
- `RAG_NVIDIA_CHAT_MODEL`
- `RAG_RERANKER_MODEL`
- `RAG_DATA_DIR`
- `RAG_MODEL_CACHE_DIR`
- `RAG_ALLOWED_ORIGINS`

Local embedding weights are stored in the application-owned model cache. If FastEmbed detects an incomplete tokenizer snapshot there, the backend preserves it and retries once in an isolated recovery subdirectory rather than continuing with a broken shared temporary cache.
