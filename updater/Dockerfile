# Updater: checks releases and switches the local stack. Works on amd64 and arm64.
FROM alpine:3.22

RUN apk add --no-cache python3 docker-cli docker-cli-compose sqlite tzdata ca-certificates

ARG VF_VERSION=0.0.0-dev
ENV VF_VERSION=${VF_VERSION} \
    VF_DATA_DIR=/data \
    PYTHONPATH=/opt/updater \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

LABEL org.opencontainers.image.source="https://github.com/japanes/images-n-videos" \
      org.opencontainers.image.title="vertexai-factory-updater" \
      org.opencontainers.image.version="${VF_VERSION}"

COPY stack/compose.yml /stack/compose.yml
COPY vf_updater /opt/updater/vf_updater

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python3", "-m", "vf_updater", "health"]

ENTRYPOINT ["python3", "-m", "vf_updater"]
CMD ["serve"]
