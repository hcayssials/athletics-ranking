# Single-image build: React front-end -> static files served by the FastAPI app.

# Stage 1 — build the front-end
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

# Stage 2 — python runtime that serves /api and the built UI
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY wa_ranking/ ./wa_ranking/
COPY data/ ./data/
COPY --from=web /web/dist ./web/dist
ENV PORT=8000
# Optional: WA_API_KEY for the unranked-profile multi-year path.
CMD ["sh", "-c", "uvicorn wa_ranking.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
