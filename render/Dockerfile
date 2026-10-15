# render: ffmpeg behind a small HTTP API (port 3000, compose network only).
# Multi-arch (linux/amd64 + linux/arm64): the base image and every package
# below are published by Debian for both, nothing is downloaded by hand.
#
# Fonts: DejaVu (Latin, Cyrillic incl. Ukrainian) is the subtitle default;
# Liberation stands in for Arial / Helvetica / Times through fontconfig's
# metric aliases, so a style that names a Windows font still renders. Brand
# fonts come from <data>/fonts at run time, never baked in.
#
# test/ is copied on purpose: `docker run --rm -v <dir>:/data <image> npm test`
# checks the code against the ffmpeg that actually ships (bookworm's 5.1),
# not the one on a developer's machine. It is a few dozen KB, no media.
FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      fontconfig \
      fonts-dejavu-core \
      fonts-liberation2 \
 && fc-cache -f \
 && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production \
    VF_DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=3000 \
    RENDER_CONCURRENCY=2

WORKDIR /app

# No runtime dependencies today; kept so adding one does not change the build.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund && rm -rf /root/.npm

COPY . .

ARG VF_VERSION=0.0.0-dev
ENV VF_VERSION=${VF_VERSION}

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=6s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/health',{signal:AbortSignal.timeout(5000)}).then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"]

# Node is PID 1 and handles SIGTERM itself (index.js): running jobs are
# aborted, their ffmpeg killed and their scratch removed before exit.
CMD ["node", "index.js"]
