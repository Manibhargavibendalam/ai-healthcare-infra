#!/usr/bin/env bash
# M3 verification: T1-T10 through the NGINX ingress (:8080). Internal
# services (ai/ehr/worker-metrics) are driven via the operator exec channel:
#   docker compose exec -T <svc> python /scripts/svc.py PORT METHOD path [body]
# (shell access, not network exposure). Fail-fast.
# Run from repo root in Git Bash:  bash scripts/m1-verify.sh
set -uo pipefail
# Git Bash on Windows mangles /container/paths for docker.exe; all paths
# in this script are container-internal, so disable conversion entirely.
export MSYS2_ARG_CONV_EXCL='*'
A=http://127.0.0.1:8080
set -a; source .env; set +a
pass=0
ok()  { echo "PASS: $1"; pass=$((pass+1)); }
die() { echo "FAIL: $1"; echo "  got: $2"; exit 1; }
have() { echo "$2" | grep -q "$3" || die "$1" "$2"; ok "$1"; }
rcli() { docker compose exec -T redis redis-cli -a "$REDIS_PASSWORD" "$@"; }
psqlq() { docker compose exec -T -e "PGPASSWORD=$POSTGRES_PASSWORD" db psql -U app -d healthcare -t -A -c "$1"; }
epost() { docker compose exec -T "$1" python /scripts/svc.py "$2" POST "$3" "$4"; }   # svc port path json
eget()  { docker compose exec -T "$1" python /scripts/svc.py "$2" GET "$3"; }         # svc port path
post_job() { curl -s -X POST "$A/api/v1/jobs" -H 'Content-Type: application/json' -d '{"type":"appointment","patient_id":1}'; }
job_id_of() { echo "$1" | grep -o '"job_id":[0-9]*' | grep -o '[0-9]*'; }
set_mode() { epost ehr 8002 /mode "{\"mode\":\"$1\"}" | grep -q '"mode": *"'"$1"'"' || die "set ehr $1" -; ok "ehr mode=$1"; }
wait_status() { # $1=id $2=want $3=max-iterations(2s each)
  for _ in $(seq 1 "$3"); do
    s=$(curl -s "$A/api/v1/jobs/$1")
    echo "$s" | grep -q "\"status\":\"$2\"" && { echo "$s"; return 0; }
    sleep 2
  done
  die "job $1 -> $2" "$s"
}

echo "== reset: hermetic start (modes to defaults) =="
docker compose start worker ai ehr >/dev/null 2>&1 || true
epost ehr 8002 /mode '{"mode":"normal"}' >/dev/null 2>&1 || true
docker compose exec -T ai python /scripts/svc.py 8001 POST /mode '{"mode":"ok"}' >/dev/null 2>&1 || true
sleep 5

echo "== T1 ingress health, registry, metrics, boundary =="
have "via nginx /health"  "$(curl -s $A/health)"                '"status":"ok"'
have "via nginx /ready"   "$(curl -s $A/ready)"                 '"status":"ready"'
have "nginx self-check"   "$(curl -s http://127.0.0.1:8080/healthz)" 'ok'
have "ai /health (exec)"  "$(eget ai 8001 /health)"             '"service": *"ai"'
have "ai /ready (exec)"   "$(eget ai 8001 /ready)"              '"status": *"ready"'
have "ehr /health (exec)" "$(eget ehr 8002 /health)"             '"mode": *"normal"'
have "patients"           "$(curl -s $A/api/v1/patients)"       'Patient-01'
have "hospitals"          "$(curl -s $A/api/v1/hospitals)"      'Test General Hospital'
have "api metrics"        "$(curl -s $A/metrics)"               'api_jobs_enqueued_total'
have "ai metrics (exec)"  "$(eget ai 8001 /metrics)"            'ai_requests_total'
have "worker metrics"     "$(eget worker 8003 /metrics)"        'jobs_processed_total'
have "request id"         "$(curl -s -D - -o /dev/null $A/health | grep -i x-request-id)" 'x-request-id'
curl -s --max-time 3 http://127.0.0.1:8000/health >/dev/null 2>&1 \
  && die "direct :8000 reachable (boundary broken)" - || ok "direct :8000 refused (ingress enforced)"

echo "== T2 api -> redis (worker stopped, queue must hold) =="
docker compose stop worker >/dev/null
J=$(post_job); ID=$(job_id_of "$J"); [ -n "$ID" ] || die "POST /api/v1/jobs" "$J"; ok "POST job -> id $ID"
echo "$J" | grep -q correlation_id || die "envelope cid in response" "$J"; ok "correlation_id returned"
have "queue depth 1" "$(rcli LLEN jobs:queue)" '^1$'

echo "== T3 worker -> redis (start, queue must drain) =="
docker compose start worker >/dev/null; sleep 10
have "queue drained" "$(rcli LLEN jobs:queue)" '^0$'
have "job $ID completed" "$(wait_status "$ID" completed 20)" '"status":"completed"'
have "heartbeat alive" "$(curl -s $A/worker/status)" '"alive":true'

echo "== T4 worker -> postgres =="
have "jobs row completed" "$(psqlq "SELECT status FROM jobs WHERE id=$ID;")" 'completed'
have "cid stored" "$(psqlq "SELECT correlation_id FROM jobs WHERE id=$ID;")" '.'
have "ehr_sync audited" "$(psqlq "SELECT status_code FROM ehr_syncs WHERE job_id=$ID;")" '200'

echo "== T5 worker -> ehr + ai =="
have "sync row" "$(psqlq "SELECT mode,status_code FROM ehr_syncs WHERE job_id=$ID;")" 'normal|200'
have "ai label kept" "$(psqlq "SELECT result FROM jobs WHERE id=$ID;")" 'label'

echo "== T6 retry w/ backoff, then recover (timeout -> normal) =="
set_mode timeout
J=$(post_job); ID2=$(job_id_of "$J")
sleep 6
have "attempt1 timed out, queued" "$(curl -s $A/api/v1/jobs/$ID2)" 'EHR timeout'
set_mode normal
S=$(wait_status "$ID2" completed 25)
have "recovered completed" "$S" '"status":"completed"'
ATT=$(echo "$S" | grep -o '"attempts":[0-9]*' | grep -o '[0-9]*'); [ "$ATT" -ge 2 ] || die "attempts>=2" "$S"; ok "attempts=$ATT (backoff then success)"

echo "== T7 failed job (temp_failure, bounded, backoff visible) =="
set_mode temp_failure
START=$(date +%s)
J=$(post_job); ID3=$(job_id_of "$J")
S=$(wait_status "$ID3" failed 30)
END=$(date +%s); ELAPSED=$((END-START))
have "failed after max" "$S" '"status":"failed"'
echo "$S" | grep -q '"attempts":3' || die "attempts==3" "$S"; ok "attempts==3, stopped retrying"
[ "$ELAPSED" -ge 6 ] || die "backoff elapsed>=6s" "${ELAPSED}s"; ok "backoff elapsed ${ELAPSED}s (>=2+4)"
have "3 sync rows" "$(psqlq "SELECT count(*) FROM ehr_syncs WHERE job_id=$ID3;")" '3'

echo "== T8 modes: slow ok / auth fail-fast / unavailable retries =="
set_mode slow
J=$(post_job); ID4=$(job_id_of "$J")
S=$(wait_status "$ID4" completed 25)
echo "$S" | grep -q '"status":"completed"' || die "slow completes" "$S"; ok "slow mode completes"
set_mode auth_failure
J=$(post_job); ID5=$(job_id_of "$J")
S=$(wait_status "$ID5" failed 20)
have "401 fail-fast" "$S" 'permanent EHR error 401'
echo "$S" | grep -q '"attempts":1' || die "401 attempts==1" "$S"; ok "401: attempts==1, zero retries"
set_mode unavailable
J=$(post_job); ID6=$(job_id_of "$J")
S=$(wait_status "$ID6" failed 30)
have "503 retried then failed" "$S" '"attempts":3'

echo "== T9 unknown outcome: HTTP 200 but NO retry =="
set_mode unknown
J=$(post_job); ID7=$(job_id_of "$J")
S=$(wait_status "$ID7" failed 20)
have "unknown failed" "$S" 'unknown EHR outcome'
echo "$S" | grep -q '"attempts":1' || die "unknown attempts==1" "$S"; ok "unknown: attempts==1, no retry"
have "sync row 200+unknown" "$(psqlq "SELECT status_code FROM ehr_syncs WHERE job_id=$ID7;")" '200'

echo "== T10 appointment books while AI is down =="
docker compose stop ai >/dev/null; sleep 3
AP=$(curl -s -X POST "$A/api/v1/appointments" -H 'Content-Type: application/json' -d '{"patient_id":1,"doctor_id":1,"scheduled_at":"2026-10-01T10:00:00"}')
echo "$AP" | grep -q '"ai_degraded":true' || { docker compose start ai >/dev/null; die "ai_degraded true" "$AP"; }
echo "$AP" | grep -q '"risk":null' || { docker compose start ai >/dev/null; die "risk null" "$AP"; }
ok "appointment created with ai_degraded=true, risk=null"
docker compose start ai >/dev/null
for _ in $(seq 1 24); do
  eget ai 8001 /health 2>/dev/null | grep -q '"status": *"ok"' && break
  sleep 5
done
AP2=$(curl -s -X POST "$A/api/v1/appointments" -H 'Content-Type: application/json' -d '{"patient_id":2,"doctor_id":2,"scheduled_at":"2026-10-02T10:00:00"}')
echo "$AP2" | grep -q '"ai_degraded":false' || die "ai recovered" "$AP2"; ok "ai recovered: risk assigned"

echo "== reset: mode normal, final healthy job =="
set_mode normal
J=$(post_job); IDF=$(job_id_of "$J")
have "final job healthy" "$(wait_status "$IDF" completed 20)" '"status":"completed"'
docker compose ps --format '{{.Name}} {{.Status}}'

echo "ALL M3 TESTS PASSED ($pass checks)"
