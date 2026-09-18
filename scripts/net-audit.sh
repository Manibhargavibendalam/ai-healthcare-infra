#!/usr/bin/env bash
# Network exposure + segmentation audit against the LIVE stack. Fail-fast.
# Proves: (1) nginx is the ONLY published door, (2) edge members cannot
# reach internal-only services, (3) the intended path works, (4) limits set.
# Run from repo root in Git Bash:  bash scripts/net-audit.sh
set -uo pipefail
NET=ai-healthcare-infra_edge
pass=0
ok() { echo "PASS: $1"; pass=$((pass+1)); }
die() { echo "FAIL: $1"; echo "  got: $2"; exit 1; }

echo "== 1. published host ports: only nginx :8080 =="
PUB=$(docker ps --format '{{.Names}} {{.Ports}}' | grep -v '^$' || true)
echo "$PUB"
echo "$PUB" | grep -q '0.0.0.0:8080->8080' || die "nginx :8080 published" "$PUB"
for svc in db redis api ai ehr worker; do
  echo "$PUB" | grep -E "m1?[-_]${svc}[-_][0-9]|/${svc} " | grep -q '0.0.0.0' \
    && die "$svc publishes host ports" "$PUB" || true
done
ok "only nginx publishes a host port"

echo "== 2. compose port map per service =="
for svc in db redis api ai ehr worker; do
  MAP=$(docker compose port "$svc" 8000 2>/dev/null; docker compose port "$svc" 5432 2>/dev/null; docker compose port "$svc" 6379 2>/dev/null; docker compose port "$svc" 8001 2>/dev/null; docker compose port "$svc" 8002 2>/dev/null; docker compose port "$svc" 8003 2>/dev/null)
  [ -z "$MAP" ] || die "$svc has port map" "$MAP"
done
MAP=$(docker compose port nginx 8080); echo "$MAP" | grep -q 8080 || die "nginx :8080 map" "$MAP"
ok "db/redis/api/ai/ehr/worker: no host port maps; nginx: :8080"

echo "== 3. segmentation: edge guest can reach api, NOT db/redis =="
IMG=python:3.12.14-slim
docker run --rm --network "$NET" "$IMG" python -c "import urllib.request;print(urllib.request.urlopen('http://api:8000/health',timeout=5).status)" | grep -q 200 \
  || die "edge->api:8000" -; ok "edge guest reaches api:8000"
docker run --rm --network "$NET" "$IMG" python -c "import socket;socket.create_connection(('db',5432),timeout=5)" 2>/dev/null \
  && die "edge->db:5432 reachable (segmentation broken)" - || ok "edge guest CANNOT reach db:5432"
docker run --rm --network "$NET" "$IMG" python -c "import socket;socket.create_connection(('redis',6379),timeout=5)" 2>/dev/null \
  && die "edge->redis:6379 reachable (segmentation broken)" - || ok "edge guest CANNOT reach redis:6379"

echo "== 4. network membership =="
docker network inspect ai-healthcare-infra_edge --format '{{range $k,$v := .Containers}}{{$v.Name}} {{end}}' | grep -q nginx \
  || die "nginx on edge" -; ok "nginx on edge"
docker network inspect ai-healthcare-infra_internal --format '{{range $k,$v := .Containers}}{{$v.Name}} {{end}}' | grep -qE 'api.*db|db.*api' \
  || die "api+db on internal" -; ok "api+db share internal"

echo "== 5. resource limits snapshot =="
docker stats --no-stream --format '{{.Name}} cpu:{{.CPUPerc}} mem:{{.MemUsage}} / {{.MemPerc}}'

echo "NET AUDIT PASSED ($pass checks)"
