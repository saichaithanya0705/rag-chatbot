# Local RAG Chat Backend

Backend for the local RAG chatbot. PDF ingestion uses IBM Docling for document parsing, OCR, table reconstruction, and source-block metadata.

## Setup

```powershell
cd D:\projects\chat\backend
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
```

## Run the API

```powershell
cd D:\projects\chat\backend
.venv\Scripts\python -m uvicorn app.main:app --reload
```

## Ingest a PDF

```powershell
cd D:\projects\chat\backend
.venv\Scripts\python scripts\ingest_pdf.py "D:\path\to\notes.pdf"
```

On first PDF ingestion, Docling downloads its layout/table/OCR artifacts into `data/docling-models` unless `RAG_DOCLING_ARTIFACTS_DIR` points somewhere else. Keep that directory writable, especially on Windows.

## Verify Ollama models

The backend defaults are configured for the models currently installed on this machine:

- Embedding model: `andersc/qwen3-embedding:0.6b`
- Chat model: `qwen3.5:4b-q4_K_M`

You can override them with environment variables:

- `RAG_OLLAMA_BASE_URL`
- `RAG_OLLAMA_EMBED_MODEL`
- `RAG_OLLAMA_CHAT_MODEL`
- `RAG_DOCLING_ARTIFACTS_DIR`
- `RAG_DOCLING_OCR`
- `RAG_DOCLING_TABLE_STRUCTURE`
- `RAG_ALLOWED_ORIGINS`
