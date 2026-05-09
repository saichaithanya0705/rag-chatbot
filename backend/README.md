# Local RAG Chat Backend

Phase 1 backend for the local RAG chatbot.

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

## Verify Ollama models

The backend defaults are configured for the models currently installed on this machine:

- Embedding model: `andersc/qwen3-embedding:0.6b`
- Chat model: `qwen3.5:4b-q4_K_M`

You can override them with environment variables:

- `RAG_OLLAMA_BASE_URL`
- `RAG_OLLAMA_EMBED_MODEL`
- `RAG_OLLAMA_CHAT_MODEL`
- `RAG_ALLOWED_ORIGINS`
