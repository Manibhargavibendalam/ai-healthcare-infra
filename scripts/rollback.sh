#!/usr/bin/env bash
# M8 rollback: re-pin `api` to a previous version and verify via ingress.
# Target defaults to the `prev` of the last deployments.jsonl entry;
# pass an explicit version to override:  bash scripts/rollback.sh v11
# Refuses when there is no history (fail-safe: never guess a version).
# Run from repo root in Git Bash.
set -uo pipefail
HISTORY="deployments.jsonl"
READY_WAIT=120

last_field() { # $1 = json key; prints value of last history line or empty
  tail -n 1 "$HISTORY" 2>/dev/null | grep -o "\"$1\":\"[^\"]*\"" | head -1 | cut -d'"' -f4 || true
}

if [ ! -s "$HISTORY" ]; then
  echo "ROLLBACK REFUSED: no $HISTORY — nothing to roll back to"
  exit 1
fi
TARGET="${1:-$(last_field prev)}"
if [ -z "$TARGET" ]; then
  echo "ROLLBACK REFUSED: last release has no prev recorded"
  exit 1
fi

echo "== rollback to $TARGET =="
export API_TAG="$TARGET"
export API_VERSION="$TARGET"
ACTOR="${DEPLOY_ACTOR:-${GITHUB_ACTOR:-$(git config user.name 2>/dev/null || whoami)}}"
docker compose up -d --no-deps api || { echo "ROLLBACK FAIL: api recreate broke"; exit 1; }

for _ in $(seq 1 $((READY_WAIT / 5))); do
  curl -s --max-time 5 http://127.0.0.1:8080/ready | grep -q '"status":"ready"' && {
    printf '{"version":"%s (rollback)","ts":"%s","actor":"%s","prev":null}\n' \
      "$TARGET" "$(date -u +%FT%TZ)" "$ACTOR" >> "$HISTORY"
    docker compose -f compose.yaml -f compose.monitoring.yaml exec -T alert-api \
      python /scripts/svc.py 8080 POST /deploys \
      "{\"version\":\"$TARGET\",\"status\":\"ok\"}" >/dev/null 2>&1 || true
    echo "ROLLBACK OK: $TARGET serving"
    exit 0
  }
  sleep 5
done
echo "ROLLBACK FAIL: $TARGET not serving — investigate api logs now"
exit 1
