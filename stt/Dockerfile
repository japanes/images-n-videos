# Local speech-to-text: faster-whisper on CPU (int8). Multi-arch: linux/amd64 + linux/arm64.
# No build toolchain and no ffmpeg binary: every dependency is a prebuilt wheel
# (PyAV wheels bundle the FFmpeg libraries). Models are downloaded at runtime
# into /data/models, never baked into the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VF_DATA_DIR=/data \
    STT_CPU_THREADS=0 \
    STT_IDLE_UNLOAD_S=600 \
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

COPY stt ./stt

ARG VF_VERSION=0.0.0-dev
ENV VF_VERSION=${VF_VERSION}

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4))['ok'] or exit(1)"]

CMD ["uvicorn", "stt.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
