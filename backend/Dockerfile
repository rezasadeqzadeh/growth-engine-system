# Build from the repo root (as app-builder): docker build -f backend/Dockerfile .
# One image for the API, the workers and the scheduler; ROLE picks what runs (entrypoint.sh).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-vazirmatn curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/growth_engine ./growth_engine
RUN pip install --no-cache-dir ".[media]"
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENV PYTHONUNBUFFERED=1 PORT=8000 STORAGE_DIR=/data/storage \
    BRAND_FONTS_DIR=/usr/share/fonts/truetype/vazirmatn
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD curl -fs http://localhost:${PORT}/api/health || exit 1
CMD ["sh", "entrypoint.sh"]
