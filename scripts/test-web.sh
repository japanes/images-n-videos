#!/usr/bin/env bash
# Frontend checks in a node:22 container: install (when package files change),
# eslint, vitest, and with --build also `nuxt generate` into web/.output/public.
# Usage: scripts/test-web.sh [--build] [--no-test]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/tmp/npm-cache" "$ROOT/tmp/locks"
exec 9>"$ROOT/tmp/locks/test-web.lock"
flock 9
BUILD=0
TEST=1
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --no-test) TEST=0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
docker run --rm -i \
  -u "$(id -u):$(id -g)" \
  -e HOME=/tmp -e npm_config_cache=/npm-cache -e npm_config_update_notifier=false \
  -e npm_config_fund=false -e npm_config_audit=false \
  -e NUXT_TELEMETRY_DISABLED=1 -e CI=1 -e BUILD="$BUILD" -e TEST="$TEST" \
  -v "$ROOT/web:/web" -v "$ROOT/tmp/npm-cache:/npm-cache" \
  -w /web node:22-bookworm-slim bash -c '
    set -e
    HASH="$(cat package.json package-lock.json 2>/dev/null | sha256sum | cut -c1-16)"
    if [ ! -f node_modules/.vf-$HASH ]; then
      if [ -f package-lock.json ]; then npm ci --no-audit; else npm install --no-audit; fi
      rm -f node_modules/.vf-*
      HASH="$(cat package.json package-lock.json | sha256sum | cut -c1-16)"
      touch node_modules/.vf-$HASH
    fi
    if [ "$TEST" = 1 ]; then
      npx eslint .
      npx vitest run
    fi
    if [ "$BUILD" = 1 ]; then
      npx nuxt generate
    fi
  '
