#!/usr/bin/env bash
# Run app checks (ruff + pytest) in a python:3.12 container with the code mounted.
# The virtualenv is kept in tmp/app-venv so repeat runs are fast.
# Usage: scripts/test-app.sh [pytest args...]   |   scripts/test-app.sh --ruff-only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/tmp/app-venv" "$ROOT/tmp/pip-cache" "$ROOT/tmp/locks"
exec 9>"$ROOT/tmp/locks/test-app.lock"
flock 9
REQ_HASH="$(cat "$ROOT/app/requirements.txt" "$ROOT/app/requirements-dev.txt" | sha256sum | cut -c1-16)"
docker run --rm -i \
  -u "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PIP_CACHE_DIR=/pip-cache -e REQ_HASH="$REQ_HASH" \
  -e VF_GOOGLE_MODE=stub \
  -v "$ROOT:/src" -v "$ROOT/tmp/app-venv:/venv" -v "$ROOT/tmp/pip-cache:/pip-cache" \
  -w /src/app python:3.12-slim bash -c '
    set -e
    if [ ! -f /venv/.req-$REQ_HASH ]; then
      rm -rf /venv/* /venv/.req-* 2>/dev/null || true
      python -m venv /venv
      /venv/bin/pip install -q --disable-pip-version-check -r requirements-dev.txt
      touch /venv/.req-$REQ_HASH
    fi
    /venv/bin/ruff check .
    if [ "${1:-}" = "--ruff-only" ]; then exit 0; fi
    /venv/bin/python -m pytest -q -p no:cacheprovider "$@"
  ' bash "$@"
