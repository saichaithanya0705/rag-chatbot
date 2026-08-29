# ──────────────────────────────────────────────────────────
# RAG Chatbot Backend — Production Dockerfile
# Includes: Python 3.11 + OpenJDK 17 JRE (for opendataloader-pdf)
# ──────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# ── System dependencies ──────────────────────────────────
# Install OpenJDK 17 JRE headless (required by opendataloader-pdf)
# and minimal build tools for native Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        default-jre-headless \
        build-essential \
        curl \
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

# ── Copy application code ───────────────────────────────
COPY . .

# ── Create data directories ─────────────────────────────
RUN mkdir -p data/uploads data/chroma data/sqlite data/kg

# ── Health check ─────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD sh -c "curl -f http://localhost:${PORT:-8000}/api/system/health || exit 1"

# ── Expose port ──────────────────────────────────────────
EXPOSE 8000

# ── Start server ─────────────────────────────────────────
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
