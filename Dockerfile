FROM node:20-alpine AS frontend-builder

WORKDIR /frontend-v2

COPY frontend-v2/package.json frontend-v2/package-lock.json ./
RUN npm ci

COPY frontend-v2/ ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend directory
COPY backend/ backend/

# Copy knowledge base into WORKDIR so config.py's Path("processed_knowledge_base") resolves
COPY processed_knowledge_base/ processed_knowledge_base/

# Copy built frontend assets
COPY --from=frontend-builder /frontend-v2/dist/ frontend-v2/dist/

# Key fix: allows `from backend.X import Y` to resolve
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8080"]
