#!/usr/bin/env bash
# Smoke test of a running Vertex AI Factory: health, web page, models API.
# Usage: scripts/smoke.sh [port]     (default: $VF_PORT or 8787)
# Used by the nightly CI run.
set -euo pipefail

PORT="${1:-${VF_PORT:-8787}}"
BASE="http://127.0.0.1:${PORT}"

fail() {
  echo "smoke: FAIL: $*" >&2
  exit 1
}

health="$(curl -fsS --max-time 10 "$BASE/health")" || fail "GET /health does not answer"
python3 -c 'import json, sys; d = json.loads(sys.argv[1]); sys.exit(0 if d.get("ok") is True and d.get("version") else 1)' \
  "$health" || fail "GET /health is not ok: $health"

page_type="$(curl -fsS --max-time 10 -o /dev/null -w '%{content_type}' "$BASE/")" \
  || fail "GET / does not answer"
case "$page_type" in
  text/html*) ;;
  *) fail "GET / is not an HTML page (Content-Type: $page_type)" ;;
esac

models="$(curl -fsS --max-time 10 "$BASE/api/models")" || fail "GET /api/models does not answer"
python3 -c 'import json, sys; json.loads(sys.argv[1])' "$models" \
  || fail "GET /api/models is not JSON"

echo "smoke: OK ($health)"
