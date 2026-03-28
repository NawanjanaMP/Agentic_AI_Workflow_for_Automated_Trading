# ── Stage 1: Build React frontend ────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY webapp/frontend/package*.json ./
RUN npm ci --silent

COPY webapp/frontend/ ./
RUN npm run build
# Output: /app/frontend/dist/

# ── Stage 2: Python backend + serve static frontend ───────────────
FROM python:3.11-slim AS backend

WORKDIR /app

# System deps (needed for numpy/scipy/faiss build wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps from backend requirements first (Docker layer cache)
COPY webapp/backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend-requirements.txt

# Install root-level requirements (backtrader, src/* models)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy project source
COPY src/         ./src/
COPY config/      ./config/
COPY data/        ./data/
COPY webapp/backend/ ./webapp/backend/

# Copy built frontend into static dir served by FastAPI
COPY --from=frontend-builder /app/frontend/dist/ ./webapp/frontend/dist/

# Expose API port
EXPOSE 8000

# Health check — hits the /api/health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

# Run Uvicorn in production mode
CMD ["uvicorn", "webapp.backend.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info"]
