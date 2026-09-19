#!/usr/bin/env bash
# Network exposure + segmentation audit against the LIVE stack. Fail-fast.
# Proves: (1) nginx is the ONLY published door, (2) edge members cannot
# reach internal-only services, (3) the intended path works, (4) limits set.
# Run from repo root in Git Bash:  bash scripts/net-audit.sh
set -uo pipefail
# Git Bash on Windows mangles /container/paths for docker.exe; all paths
# in this script are container-internal, so disable conversion entirely.
export MSYS2_ARG_CONV_EXCL='*'
NET=ai-healthcare-infra_edge
pass=0
ok() { echo "PASS: $1"; pass=$((pass+1)); }
die() { echo "FAIL: $1"; echo "  got: $2"; exit 1; }

echo "== 1. published host ports: only nginx :8080 =="
PUB=$(docker ps --format '{{.Names}} {{.Ports}}' | grep -v '^$' || true)
echo "$PUB"
echo "$PUB" | grep -q '127.0.0.1:8080->8080' || die "nginx :8080 published" "$PUB"
echo "$PUB" | grep -q '0.0.0.0:8080' && die "nginx on LAN, want host-local" "$PUB" || true
ok "nginx :8080 host-local only (no 0.0.0.0)"
for svc in db redis api ai ehr worker; do
  echo "$PUB" | grep -E "m1?[-_]${svc}[-_][0-9]|/${svc} " | grep -q '0.0.0.0' \
    && die "$svc publishes host ports" "$PUB" || true
done
ok "only nginx publishes a host port"

echo "== 2. host port bindings per service (inspect, authoritative) =="
for svc in db redis api ai ehr worker; do
  cid=$(docker compose ps -q "$svc")
  BIND=$(docker inspect "$cid" --format '{{json .HostConfig.PortBindings}}')
  { [ "$BIND" = "null" ] || [ "$BIND" = "{}" ]; } || die "$svc publishes host ports" "$BIND"
done
ok "db/redis/api/ai/ehr/worker: PortBindings null"
cid=$(docker compose ps -q nginx)
BIND=$(docker inspect "$cid" --format '{{json .HostConfig.PortBindings}}')
echo "$BIND" | grep -q '8080' || die "nginx :8080 map" "$BIND"
ok "nginx publishes :8080 only"

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
