FROM node:20-alpine AS frontend-builder

WORKDIR /frontend-v2

COPY frontend-v2/package.json frontend-v2/package-lock.json ./
RUN npm ci

COPY frontend-v2/ ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

# Pango runtime for weasyprint (answer-export PDF pipeline). Kept minimal —
# pango + gobject are what weasyprint actually dlopens; shared-mime-info lets
# font fallback resolve cleanly. No build toolchain needed (weasyprint is pure
# Python above these shared libs).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cached layer)
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Install bottl-commons from vendored wheel
COPY vendor/ vendor/
RUN pip install --no-cache-dir vendor/*.whl && rm -rf vendor/

# Copy backend directory
COPY backend/ backend/

# Copy knowledge base into WORKDIR so config.py's Path("processed_knowledge_base") resolves.
# .dockerignore excludes the 932MB embeddings_cache.json — only the pre-built
# 167MB .npy file (and chunk JSONs) are shipped, keeping the image small and
# avoiding the 3.8GB peak-RAM JSON→numpy conversion inside the builder.
COPY processed_knowledge_base/ processed_knowledge_base/

# Safety net: if someone removes the .npy locally, re-generate it at build time.
# In normal operation the .npy already exists and the script exits immediately.
COPY scripts/convert_embeddings_to_npy.py scripts/convert_embeddings_to_npy.py
RUN python scripts/convert_embeddings_to_npy.py --kb-dir processed_knowledge_base \
    && rm -f processed_knowledge_base/embeddings_cache.json

# Copy built frontend assets
COPY --from=frontend-builder /frontend-v2/dist/ frontend-v2/dist/

# Key fix: allows `from backend.X import Y` to resolve
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8080"]
