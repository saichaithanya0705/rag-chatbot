# Local RAG Chat Backend

Backend for the local RAG chatbot. PDF ingestion uses IBM Docling for document parsing, OCR, table reconstruction, and source-block metadata.

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

On first PDF ingestion, Docling downloads its layout/table/OCR artifacts into `data/docling-models` unless `RAG_DOCLING_ARTIFACTS_DIR` points somewhere else. Keep that directory writable, especially on Windows.

## Verify Ollama models

The backend defaults are configured for the models currently installed on this machine:

- Embedding model: `all-minilm` (384-dimensional embeddings)
- Chat model: `gemma4:31b-cloud`

You can override them with environment variables:

- `RAG_OLLAMA_BASE_URL`
- `RAG_OLLAMA_EMBED_MODEL`
- `RAG_EMBEDDING_DIMENSIONS`
- `RAG_OLLAMA_CHAT_MODEL`
- `RAG_DOCLING_ARTIFACTS_DIR`
- `RAG_DOCLING_OCR`
- `RAG_DOCLING_TABLE_STRUCTURE`
- `RAG_ALLOWED_ORIGINS`
