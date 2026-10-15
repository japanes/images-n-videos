#!/usr/bin/env bash
# End-to-end test of installation and updates with fake app/render/stt images.
#
# Runs a local registry and a fake GitHub Releases API, then checks with the
# real updater image and the real release/compose.yml:
#   1. first start from the launcher installs 0.1.0;
#   2. a manual update to 0.2.0 (backup, prepare call to the app, switch);
#   3. a broken 0.3.0 is rolled back to 0.2.0 together with the database;
#   4. starting the launcher again hands control back to the installed 0.2.0;
#   5. "stop" from the updater stops everything.
#
# Needs docker with compose v2, curl and python3. Touches only names that
# start with vf-e2e and images under localhost:$E2E_REGISTRY_PORT/vf-e2e.
# Env: E2E_WORK (work dir, default <repo>/tmp/updater/e2e), E2E_REGISTRY_PORT
# (55000), E2E_APP_PORT (58787), E2E_KEEP=1 (leave everything running).
# "e2e.sh --clean" only removes what an earlier E2E_KEEP=1 run left.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SRC="$HERE/e2e"
WORK="${E2E_WORK:-$ROOT/tmp/updater/e2e}"
REG_PORT="${E2E_REGISTRY_PORT:-55000}"
APP_PORT="${E2E_APP_PORT:-58787}"
PREFIX="localhost:${REG_PORT}/vf-e2e"
PROJECT="vf-e2e"
VOLUME="vf-e2e-data"
NETWORK="${PROJECT}_default"
REGISTRY="vf-e2e-registry"
API="vf-e2e-api"
HELPER="${PROJECT}-update-helper"
LAUNCHER="$ROOT/release/compose.yml"

export VF_PROJECT="$PROJECT" VF_DATA_VOLUME="$VOLUME" VF_IMAGE_PREFIX="$PREFIX" \
  VF_RELEASES_API="http://${API}:8000/releases" VF_PORT="$APP_PORT" \
  VF_VERIFY_TIMEOUT=60 VF_GOOGLE_MODE=stub
unset VF_CHANNEL_TAG VF_UPDATER_DEV

log() { printf '\n== %s\n' "$*"; }

compose() { docker compose -p "$PROJECT" -f "$LAUNCHER" "$@"; }

# Read a value from JSON on stdin: jget 'd["state"]'
jget() { python3 -c 'import json, sys; d = json.load(sys.stdin); print(eval(sys.argv[1]))' "$1"; }

# Call the updater API from inside the compose network (token from the data volume).
api() { docker exec "$API" python3 /src/fake_api.py call "$@"; }

dump() {
  echo "---- containers"
  docker ps -a --filter "label=com.docker.compose.project=$PROJECT" \
    --format '{{.Names}} {{.Image}} {{.Status}}' || true
  echo "---- updater log"
  docker logs --tail 60 "${PROJECT}-updater-1" 2>&1 || true
  echo "---- op.json"
  docker exec "$API" cat /data/update/op.json 2>/dev/null || true
  echo "---- app log"
  docker exec "$API" cat /data/e2e-app.log 2>/dev/null || true
}

fail() {
  echo "E2E FAILED: $*" >&2
  dump >&2
  exit 1
}

cleanup() {
  local ids refs
  if [ "${E2E_KEEP:-}" = "1" ]; then
    echo "E2E_KEEP=1: leaving the test containers running"
    return
  fi
  docker rm -f "$API" "$HELPER" >/dev/null 2>&1 || true
  compose down --remove-orphans --timeout 5 >/dev/null 2>&1 || true
  ids="$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")"
  if [ -n "$ids" ]; then echo "$ids" | xargs docker rm -f >/dev/null 2>&1 || true; fi
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  docker rm -f -v "$REGISTRY" >/dev/null 2>&1 || true
  for _ in 1 2 3; do
    refs="$(docker images --digests --format '{{.Repository}} {{.Tag}} {{.Digest}}' |
      awk -v p="$PREFIX/" 'index($1, p) == 1 {
        if ($2 != "<none>") print $1 ":" $2; else if ($3 != "<none>") print $1 "@" $3 }' |
      sort -u)"
    [ -z "$refs" ] && break
    echo "$refs" | xargs docker rmi >/dev/null 2>&1 || true
  done
}

# wait_for DESCRIPTION SECONDS COMMAND... : repeat COMMAND every 3 s until it succeeds.
wait_for() {
  local what="$1" limit="$2" start
  shift 2
  start="$(date +%s)"
  until "$@" >/dev/null 2>&1; do
    if [ $(( $(date +%s) - start )) -ge "$limit" ]; then
      fail "timed out after ${limit}s waiting for: $what"
    fi
    sleep 3
  done
  echo "ok: $what ($(( $(date +%s) - start ))s)"
}

app_version_is() {
  [ "$(curl -fsS --max-time 3 "http://127.0.0.1:${APP_PORT}/health" | jget 'd["version"]')" = "$1" ]
}

updater_version_is() {
  [ "$(docker exec "$API" python3 -c 'import urllib.request; print(urllib.request.urlopen("http://updater:8080/health", timeout=3).read().decode())' |
    jget 'd["version"]')" = "$1" ]
}

# status_ok PYTHON_CONDITION: the updater status matches the condition (d = status).
status_ok() {
  local out
  out="$(api GET /status)" || return 1
  [ "$(printf '%s' "$out" | jget "bool($1)")" = "True" ]
}

# check_shows "0.2.0": a manual check lists exactly these versions as available.
check_shows() {
  local out
  out="$(api POST /check)" || return 1
  [ "$(printf '%s' "$out" | jget '" ".join(a["version"] for a in d["available"])')" = "$1" ]
}

stack_images() {
  docker ps --filter "label=com.docker.compose.project=$PROJECT" \
    --format '{{.Label "com.docker.compose.service"}}={{.Image}}' | sort | tr '\n' ' '
}

expect_stack() {
  local want="app=$PREFIX/app:$1 render=$PREFIX/render:$1 stt=$PREFIX/stt:$1 updater=$PREFIX/updater:$1 "
  [ "$(stack_images)" = "$want" ] || fail "stack is '$(stack_images)', expected '$want'"
}

stack_is() {
  local want="app=$PREFIX/app:$1 render=$PREFIX/render:$1 stt=$PREFIX/stt:$1 updater=$PREFIX/updater:$1 "
  [ "$(stack_images)" = "$want" ]
}

nothing_running() {
  [ -z "$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT")" ]
}

assert() {
  # assert DESCRIPTION PYTHON_CONDITION JSON
  local result
  result="$(printf '%s' "$3" | jget "bool($2)")" || fail "$1: cannot evaluate"
  [ "$result" = "True" ] || fail "$1: $(printf '%s' "$3" | head -c 1500)"
  echo "ok: $1"
}

registry_digest() {
  # Digest of PREFIX/<service>:<tag> as stored in the registry.
  curl -fsSI \
    -H 'Accept: application/vnd.oci.image.index.v1+json' \
    -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
    -H 'Accept: application/vnd.docker.distribution.manifest.list.v2+json' \
    -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
    "http://127.0.0.1:${REG_PORT}/v2/vf-e2e/$1/manifests/$2" |
    tr -d '\r' | awk -F': ' 'tolower($1) == "docker-content-digest" { print $2 }'
}

# quiet COMMAND...: run COMMAND, show its output only when it fails.
quiet() {
  "$@" > "$WORK/last-command.log" 2>&1 || { cat "$WORK/last-command.log" >&2; fail "command failed: $*"; }
}

build_version() {
  local v="$1" broken="${2:-0}" svc
  quiet docker build -f "$SRC/Dockerfile.python" --build-arg FAKE_ROLE=app \
    --build-arg FAKE_VERSION="$v" --build-arg FAKE_PORT=8787 --build-arg FAKE_BROKEN="$broken" \
    -t "$PREFIX/app:$v" "$SRC"
  quiet docker build -f "$SRC/Dockerfile.python" --build-arg FAKE_ROLE=stt \
    --build-arg FAKE_VERSION="$v" --build-arg FAKE_PORT=8000 -t "$PREFIX/stt:$v" "$SRC"
  quiet docker build -f "$SRC/Dockerfile.render" --build-arg FAKE_VERSION="$v" \
    -t "$PREFIX/render:$v" "$SRC"
  quiet docker build --build-arg VF_VERSION="$v" -t "$PREFIX/updater:$v" "$ROOT/updater"
  : > "$WORK/digests/$v.env"
  for svc in app render stt updater; do
    quiet docker push "$PREFIX/$svc:$v"
    echo "$svc=$(registry_digest "$svc" "$v")" >> "$WORK/digests/$v.env"
  done
  grep -q '=$' "$WORK/digests/$v.env" && fail "no digest for some image of $v"
  echo "built and pushed $v"
}

publish() { python3 "$SRC/fake_api.py" publish "$WORK/api" "$1" "$PREFIX" "$WORK/digests/$1.env" "${@:2}"; }

if [ "${1:-}" = "--clean" ]; then
  E2E_KEEP=0 cleanup
  exit 0
fi
trap cleanup EXIT
cleanup
rm -rf "$WORK"
mkdir -p "$WORK/api" "$WORK/digests"

log "local registry on 127.0.0.1:$REG_PORT"
docker run -d --name "$REGISTRY" -p "127.0.0.1:${REG_PORT}:5000" registry:2 >/dev/null
wait_for "registry" 60 curl -fsS "http://127.0.0.1:${REG_PORT}/v2/"

log "build and push fake versions"
build_version 0.1.0
build_version 0.2.0
build_version 0.3.0 1
docker tag "$PREFIX/updater:0.1.0" "$PREFIX/updater:stable"
quiet docker push "$PREFIX/updater:stable"
# Drop local copies so that every image below really comes from the registry.
for v in 0.1.0 0.2.0 0.3.0; do
  for svc in app render stt updater; do docker rmi "$PREFIX/$svc:$v" >/dev/null; done
done
docker rmi "$PREFIX/updater:stable" >/dev/null
publish 0.1.0

log "1. first start from the launcher"
compose up --no-start --quiet-pull
docker run -d --name "$API" --network "$NETWORK" -v "$VOLUME:/data:ro" -v "$SRC:/src:ro" \
  -v "$WORK/api:/api:ro" python:3.12-slim python3 /src/fake_api.py serve /api >/dev/null
compose up -d
wait_for "app 0.1.0 answers on 127.0.0.1:$APP_PORT" 300 app_version_is 0.1.0
wait_for "installed 0.1.0 and idle" 180 status_ok 'd["installed_version"] == "0.1.0" and d["state"] == "idle" and d["current_version"] == "0.1.0"'
expect_stack 0.1.0
history="$(api GET /history)"
assert "history has the first install" \
  'd["items"][0]["kind"] == "apply" and d["items"][0]["result"] == "success" and d["items"][0]["version_to"] == "0.1.0"' \
  "$history"
assert "auto updates switched off" 'd["auto"] is False' "$(api POST /settings '{"auto": false}')"

log "2. manual update to 0.2.0"
publish 0.2.0
publish 0.4.0-beta.1 --prerelease --no-manifest
wait_for "check lists 0.2.0 only (no beta on the stable channel)" 150 check_shows "0.2.0"
assert "install accepted" 'd["ok"] is True and d["operation"]["to"] == "0.2.0"' \
  "$(api POST /install '{"version": "0.2.0"}')"
wait_for "update to 0.2.0 finished" 300 status_ok 'd["operation"] and d["operation"]["to"] == "0.2.0" and not d["operation"]["active"]'
status="$(api GET /status)"
assert "update succeeded" \
  'd["operation"]["result"] == "success" and d["state"] == "done" and d["installed_version"] == "0.2.0" and d["current_version"] == "0.2.0" and d["error"] is None' \
  "$status"
app_version_is 0.2.0 || fail "app does not report 0.2.0"
updater_version_is 0.2.0 || fail "updater does not report 0.2.0"
expect_stack 0.2.0
history="$(api GET /history)"
assert "history has the update with a database copy" \
  'd["items"][0]["version_from"] == "0.1.0" and d["items"][0]["version_to"] == "0.2.0" and d["items"][0]["result"] == "success" and d["items"][0]["backup_file"]' \
  "$history"
backup_file="$(printf '%s' "$history" | jget 'd["items"][0]["backup_file"]')"
docker exec "$API" test -s "$backup_file" || fail "backup file $backup_file is missing"
docker exec "$API" test -s /data/update/stacks/0.2.0/compose.yml || fail "stack file of 0.2.0 is missing"
docker exec "$API" grep -q "prepare 0.2.0 ttl=1800 from=0.1.0" /data/e2e-app.log \
  || fail "the app was not asked to prepare"
echo "ok: backup $backup_file, stack file, prepare call"
if [ -x "$ROOT/release/smoke.sh" ]; then "$ROOT/release/smoke.sh" "$APP_PORT"; fi

log "3. broken 0.3.0 rolls back"
publish 0.3.0
wait_for "check lists 0.3.0" 150 check_shows "0.3.0"
assert "install accepted" 'd["ok"] is True' "$(api POST /install '{"version": "0.3.0"}')"
wait_for "update to 0.3.0 finished" 420 status_ok 'd["operation"] and d["operation"]["to"] == "0.3.0" and not d["operation"]["active"]'
status="$(api GET /status)"
assert "update was rolled back" \
  'd["operation"]["result"] == "rolled_back" and d["state"] == "failed" and d["installed_version"] == "0.2.0" and d["current_version"] == "0.2.0" and "0.2.0 was restored" in d["error"]' \
  "$status"
assert "0.3.0 is marked as failed before" \
  '[(a["version"], a["failed_before"]) for a in d["available"]] == [("0.3.0", True)]' "$status"
app_version_is 0.2.0 || fail "app does not report 0.2.0 after the rollback"
expect_stack 0.2.0
rows="$(docker exec "$API" python3 /src/fake_api.py rows)"
assert "database restored from the copy" \
  '"booted 0.3.0" not in d and "booted 0.2.0" in d and "booted 0.1.0" in d' "$rows"
docker exec "$API" grep -q "resume from=0.2.0" /data/e2e-app.log \
  || fail "the app was not told to resume after the rollback"
assert "history has the rollback" \
  'd["items"][0]["version_to"] == "0.3.0" and d["items"][0]["result"] == "rolled_back"' \
  "$(api GET /history)"

log "4. starting the launcher again hands over to the installed version"
COMPOSE_IGNORE_ORPHANS=1 compose up -d
[ "$(docker inspect --format '{{.Config.Image}}' "${PROJECT}-updater-1")" = "$PREFIX/updater:stable" ] \
  || fail "the launcher did not start the stable updater"
wait_for "updater 0.2.0 is back" 240 updater_version_is 0.2.0
wait_for "installed 0.2.0, nothing running" 120 status_ok 'd["installed_version"] == "0.2.0" and d["current_version"] == "0.2.0" and (d["operation"] is None or not d["operation"]["active"])'
wait_for "all services on 0.2.0" 60 stack_is 0.2.0
app_version_is 0.2.0 || fail "app does not report 0.2.0 after the hand-over"

log "5. stop from the updater"
assert "stop accepted" 'd == {"ok": True}' "$(api POST /stop)"
wait_for "all containers stopped" 120 nothing_running
compose down --remove-orphans --timeout 5 >/dev/null 2>&1
[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ] \
  || fail "containers left after 'compose down --remove-orphans'"
echo "ok: stop script command removes everything"

log "E2E PASSED"
