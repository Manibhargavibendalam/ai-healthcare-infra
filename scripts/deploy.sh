#!/usr/bin/env bash
# M8/M11 verify-before-replace deploy (blue/green without an orchestrator).
# Healthy path (10 steps): structural gate -> build+tag -> candidate up ->
# /ready gate -> smoke dependencies -> replace api -> ingress verify ->
# version-under-traffic check -> smoke enqueue -> retire candidate ->
# record + post ok.
# Broken path: any gate fails -> candidate destroyed, api untouched (or
# auto-rollback after a bad switch), failed posted, exit 1.
# Usage:  bash scripts/deploy.sh v2            (healthy release)
#         bash scripts/deploy.sh v3 --broken   (v3-style failure drill:
#            candidate /ready 503s via BREAK_READY, release blocked, old serves)
# CI calls it with the commit sha. Needs the base stack already up.
set -uo pipefail
# Git Bash on Windows mangles /container/paths for docker.exe; all paths
# in this script are container-internal, so disable conversion entirely.
export MSYS2_ARG_CONV_EXCL='*'
VERSION="${1:?usage: bash scripts/deploy.sh <version> [--broken]}"
export API_TAG="$VERSION"
export API_VERSION="$VERSION" # surfaces in GET /health + api_build_info
if [ "${2:-}" = "--broken" ]; then
  export BREAK_READY=1
  echo "== drill mode: candidate will fail readiness (BREAK_READY=1) =="
else
  export BREAK_READY=0
fi
HISTORY="deployments.jsonl"
READY_WAIT=120
SMOKE_WAIT=60
DEPLOY_T0=$(date +%s)

gate_config() {
  docker compose config --quiet \
    || { echo "DEPLOY ABORT: compose config invalid (structural gate)"; return 1; }
}

post_deploy() { # $1 = ok|failed — best effort: monitoring overlay may be down
  docker compose -f compose.yaml -f compose.monitoring.yaml exec -T alert-api \
    python /scripts/svc.py 8080 POST /deploys \
    "{\"version\":\"$VERSION\",\"status\":\"$1\"}" >/dev/null 2>&1 || true
}

candidate_ready() { # poll /ready INSIDE the candidate (internal-only, via exec)
  for _ in $(seq 1 $((READY_WAIT / 5))); do
    out=$(docker compose -f compose.yaml -f compose.candidate.yaml exec -T \
      api-candidate python /scripts/svc.py 8000 GET /ready 2>/dev/null || true)
    echo "$out" | head -1 | grep -q '^200' && echo "$out" | grep -q '"status":"ready"' \
      && return 0
    sleep 5
  done
  return 1
}

ingress_ready() { # poll the PUBLIC path after the switch
  for _ in $(seq 1 $((READY_WAIT / 5))); do
    curl -s --max-time 5 http://127.0.0.1:8080/ready | grep -q '"status":"ready"' \
      && return 0
    sleep 5
  done
  return 1
}

ACTOR="${DEPLOY_ACTOR:-${GITHUB_ACTOR:-$(git config user.name 2>/dev/null || whoami)}}"
record_ok() { # append release to history (JSONL: grep/cut only, no jq/python)
  prev=$(tail -n 1 "$HISTORY" 2>/dev/null | grep -o '"version":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
  if [ -n "${prev:-}" ]; then prev_json="\"$prev\""; else prev_json="null"; fi
  printf '{"version":"%s","ts":"%s","actor":"%s","duration_s":%d,"prev":%s}\n' \
    "$VERSION" "$(date -u +%FT%TZ)" "$ACTOR" "$(( $(date +%s) - DEPLOY_T0 ))" \
    "$prev_json" >> "$HISTORY"
}

echo "== deploy $VERSION: structural gate =="
gate_config || exit 1

echo "== build healthcare-api:$VERSION =="
docker compose build api || { echo "DEPLOY FAIL: build broke"; post_deploy failed; exit 1; }

echo "== candidate up =="
docker compose -f compose.yaml -f compose.candidate.yaml up -d api-candidate \
  || { echo "DEPLOY FAIL: candidate would not start"; post_deploy failed; exit 1; }

echo "== readiness gate (candidate /ready, ${READY_WAIT}s) =="
if ! candidate_ready; then
  echo "DEPLOY FAIL: candidate never ready — api untouched, still serving old version"
  docker compose -f compose.yaml -f compose.candidate.yaml rm -sf api-candidate >/dev/null
  post_deploy failed
  exit 1
fi
echo "candidate READY"

echo "== switch: recreate api from verified tag =="
docker compose up -d --no-deps api || {
  echo "DEPLOY FAIL: api recreate broke — candidate kept for inspection"
  post_deploy failed; exit 1; }

echo "== verify via ingress (:8080/ready, ${READY_WAIT}s) =="
if ! ingress_ready; then
  echo "DEPLOY FAIL: api not serving after switch — auto-rollback NOW"
  post_deploy failed
  bash scripts/rollback.sh || true
  exit 1
fi

echo "== smoke: version under traffic + deps + enqueue (api-owned) =="
smoke_ok=1
ver=$(curl -s --max-time 5 http://127.0.0.1:8080/health | grep -o '"version":"[^"]*"' || true)
echo "serving version: $ver (want \"$VERSION\")"
echo "$ver" | grep -q "\"version\":\"$VERSION\"" || smoke_ok=0
curl -s --max-time 5 http://127.0.0.1:8080/api/v1/db/stats | grep -q query_ms \
  || { echo "SMOKE FAIL: db/stats"; smoke_ok=0; }
job=$(curl -s --max-time 5 -X POST http://127.0.0.1:8080/api/v1/jobs \
  -H 'Content-Type: application/json' -d '{"type":"smoke","patient_id":1}' || true)
echo "$job" | grep -q '"job_id"' || { echo "SMOKE FAIL: enqueue"; smoke_ok=0; }
if [ "$smoke_ok" = 0 ]; then
  echo "DEPLOY FAIL: smoke test red — auto-rollback NOW"
  post_deploy failed
  bash scripts/rollback.sh || true
  exit 1
fi
echo "smoke GREEN (version match, deps ok, job accepted)"

echo "== retire candidate, record release =="
docker compose -f compose.yaml -f compose.candidate.yaml rm -sf api-candidate >/dev/null
record_ok
post_deploy ok
echo "DEPLOY OK: $VERSION serving (api_build_info will confirm in Prometheus)"
