# ──────────────────────────────────────────────────────────
# RAG Chatbot Backend — small OpenDataLoader runtime
# ──────────────────────────────────────────────────────────

FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b

# ── System dependencies ──────────────────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# Verify Java is available
RUN java -version

# ── Python environment ───────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── Install Python dependencies ─────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --system rag && useradd --system --gid rag --home-dir /app rag

COPY --chown=rag:rag . .

# ── Create data directories ─────────────────────────────
RUN mkdir -p data/uploads data/chroma data/celery && chown -R rag:rag data

USER rag

# ── Health check ─────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/api/system/ready', timeout=5)"

# ── Expose port ──────────────────────────────────────────
EXPOSE 8000

# ── Start server ─────────────────────────────────────────
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
