# app: FastAPI backend + the built web interface, one image.
# Build context is the repository root: docker build -f app/Dockerfile .
# Multi-arch (linux/amd64 + linux/arm64). The web stage runs on the build
# machine's own platform: its output is plain static files.

ARG BUILDPLATFORM=linux/amd64
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS web
ENV NUXT_TELEMETRY_DISABLED=1 CI=1
WORKDIR /web
COPY web/package.json web/package-lock.json web/.npmrc ./
RUN npm ci --no-audit --no-fund --ignore-scripts
COPY web/ ./
RUN npx nuxt generate

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VF_DATA_DIR=/data \
    VF_WEB_DIR=/srv/web

WORKDIR /srv/app
COPY app/requirements.txt ./
RUN pip install --only-binary=:all: -r requirements.txt

COPY app/ ./
COPY --from=web /web/.output/public /srv/web

ARG VF_VERSION=0.0.0-dev
ENV VF_VERSION=${VF_VERSION}
LABEL org.opencontainers.image.source="https://github.com/japanes/images-n-videos" \
      org.opencontainers.image.title="vertexai-factory-app" \
      org.opencontainers.image.version="${VF_VERSION}"

EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=4))['ok'] or exit(1)"]

CMD ["python", "-m", "vf"]
