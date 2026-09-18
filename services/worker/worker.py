"""Background worker (M2 simulation).

Loop: (1) promote due delayed-retries (jobs:delayed ZSET -> jobs:queue),
(2) BRPOPLPUSH jobs:queue -> jobs:processing (blocking), so a mid-job crash
leaves the item visible instead of losing it.
Per job: mark processing (attempts+1) -> POST EHR /sync (timeout) ->
classify result -> on ok POST AI /process -> mark completed.
Failure policy (also see classify/retry_delay pure functions, unit-tested):
  temporary (timeout/conn/429/5xx) -> delayed requeue with exponential
      backoff while attempts < MAX_ATTEMPTS, else failed;
  permanent (400/401/403/404/422) -> failed immediately, never retried;
  unknown (HTTP 200 + outcome=unknown) -> failed WITHOUT retry and a
      reconciliation-required error (retrying could double-apply server-side).
Liveness/health/metrics: stdlib HTTP server on WORKER_METRICS_PORT (8003):
  /health (alive + uptime), /ready (redis+db reachable), /metrics
  (Prometheus text, hand-rolled: same wire format, zero extra deps).
  Restarts survive as a Redis counter (INCR at startup).
Correlation: envelope carries correlation_id; forwarded as X-Request-ID to
EHR/AI and stamped on every log line, so one job traces end-to-end.
"""
import json
import os
import signal
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg2
import redis
import requests


def _num(name, default, kind=float):
    # Fail fast with a USEFUL message on bad config (F7): a clear
    # "invalid VAR='x'" beats a bare ValueError traceback at 2am.
    raw = os.environ.get(name, default)
    try:
        return kind(raw)
    except (ValueError, TypeError):
        print(json.dumps({"svc": "worker", "event": "bad_config",
                          "var": name, "value": raw}), flush=True)
        raise SystemExit(f"invalid {name}={raw!r}: must be a number")


DB_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
EHR_URL = os.environ.get("EHR_URL", "http://ehr:8002")
AI_URL = os.environ.get("AI_URL", "http://ai:8001")
TIMEOUT = _num("WORKER_TIMEOUT_SEC", "5")
MAX_ATTEMPTS = _num("MAX_ATTEMPTS", "3", int)
HB_EVERY = _num("HEARTBEAT_SEC", "5")
METRICS_PORT = _num("WORKER_METRICS_PORT", "8003", int)
BACKOFF_BASE = _num("BACKOFF_BASE_SEC", "2")
BACKOFF_CAP = _num("BACKOFF_CAP_SEC", "30")
QUEUE = "jobs:queue"
PROCESSING = "jobs:processing"
DELAYED = "jobs:delayed"
TEMP_CODES = {408, 425, 429, 500, 502, 503, 504}
PERM_CODES = {400, 401, 403, 404, 422}

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
STARTED = time.time()
DRAINING = False


def _on_term(signum, frame):  # graceful: finish current job, take no new ones
    global DRAINING
    DRAINING = True
    log(event="draining", signal=signum)


def log(cid="none", level="info", operation=None, job_id=None,
        status=None, duration_ms=None, dependency=None, error=None, **fields):
    """Structured log event (M6). Keyword `event=` from older call sites maps
    to `op` so one schema covers history: ts/level/svc/cid/op always present."""
    op = fields.pop("event", operation or "worker")
    rec = {"ts": datetime.now(UTC).isoformat(),
           "level": level, "svc": "worker", "cid": cid, "op": op}
    if job_id is not None:
        rec["job_id"] = job_id
    if status is not None:
        rec["status"] = status
    if duration_ms is not None:
        rec["duration_ms"] = duration_ms
    if dependency is not None:
        rec["dependency"] = dependency
    if error is not None:
        rec["error"] = str(error)[:300]
    rec.update(fields)
    print(json.dumps(rec), flush=True)


def classify(status_code, body):
    """Pure EHR-result classifier (unit-tested).

    ok: HTTP 200 with outcome=applied. unknown: HTTP 200 with
    outcome=unknown (ambiguous — must NOT auto-retry). permanent:
    caller-side/auth errors. temporary: everything else, including
    connection-level failures (status_code None) and unlisted codes
    (bounded retries make retrying the safe default).
    """
    body = body or {}
    if status_code == 200:
        return "unknown" if body.get("outcome") == "unknown" else "ok"
    if status_code in PERM_CODES:
        return "permanent"
    return "temporary"


def retry_delay(failed_attempt, base=BACKOFF_BASE, cap=BACKOFF_CAP):
    """Pure exponential backoff (unit-tested): 2s, 4s, 8s... capped."""
    return min(cap, base * (2 ** (failed_attempt - 1)))


def heartbeat():
    r.set("worker:heartbeat", time.time())


def get_attempts(job_id):
    conn = psycopg2.connect(DB_URL)
    try:
        cur = conn.cursor()
        cur.execute("SELECT attempts, max_attempts FROM jobs WHERE id = %s", (job_id,))
        return cur.fetchone()
    finally:
        conn.close()


def mark(job_id, status, result=None, error=None, processing_ms=None):
    conn = psycopg2.connect(DB_URL)
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE jobs SET status=%s, result=%s, error=%s, processing_ms=%s,
               updated_at=now() WHERE id=%s""",
            (status, result, error, processing_ms, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def record_sync(job_id, mode, code, ms, err):
    conn = psycopg2.connect(DB_URL)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ehr_syncs(job_id, mode, status_code, latency_ms, error)"
            " VALUES (%s, %s, %s, %s, %s)",
            (job_id, mode, code, ms, err),
        )
        conn.commit()
    finally:
        conn.close()


def ehr_mode():
    try:
        return requests.get(f"{EHR_URL}/mode", timeout=3).json().get("mode", "unknown")
    except Exception:  # EHR unreachable => mode unknown
        return "unknown"


def retry_or_fail(job_id, cid, err):
    row = get_attempts(job_id)
    attempts = row[0] if row else MAX_ATTEMPTS
    if attempts < MAX_ATTEMPTS:
        delay = retry_delay(attempts)
        mark(job_id, "queued", error=err)
        payload = json.dumps({"job_id": job_id, "correlation_id": cid,
                              "attempts": attempts, "enqueued_at": time.time()})
        r.zadd(DELAYED, {payload: time.time() + delay})
        r.hincrby("worker:stats", "retried", 1)
        log(cid, event="retry", job_id=job_id, attempt=attempts,
            backoff_s=delay, error=err)
    else:
        mark(job_id, "failed", error=err)
        r.hincrby("worker:stats", "failed", 1)
        log(cid, event="failed", job_id=job_id, attempts=attempts, error=err)


def handle(item):
    try:
        env = json.loads(item)
        job_id, cid = env["job_id"], env.get("correlation_id", "none")
    except Exception:  # poison message: drop it, keep looping
        r.lrem(PROCESSING, 1, item)
        log(event="dropped_poison_message")
        return
    row = get_attempts(job_id)
    if row is None:
        log(cid, event="skip", job_id=job_id, reason="no DB row")
        return
    attempts = row[0] + 1
    conn = psycopg2.connect(DB_URL)
    try:
        cur = conn.cursor()
        cur.execute("UPDATE jobs SET status='processing', attempts=%s,"
                    " updated_at=now() WHERE id=%s", (attempts, job_id))
        conn.commit()
    finally:
        conn.close()
    log(cid, event="start", job_id=job_id, attempt=attempts)
    t0 = time.time()
    headers = {"X-Request-ID": cid}
    try:
        resp = requests.post(f"{EHR_URL}/sync", json={"job_id": job_id},
                             headers=headers, timeout=TIMEOUT)
        ms = int((time.time() - t0) * 1000)
        try:
            body = resp.json()
        except Exception:  # non-JSON error page: classify by status code
            body = {}
        record_sync(job_id, body.get("mode", "unknown"), resp.status_code, ms, None)
        verdict = classify(resp.status_code, body)
        if verdict == "ok":
            ai = requests.post(f"{AI_URL}/process", json={"job_id": job_id},
                               headers=headers, timeout=TIMEOUT).json()
            total = int((time.time() - t0) * 1000)
            mark(job_id, "completed",
                 result=json.dumps({"ehr": body, "ai": ai}), processing_ms=total)
            r.hincrby("worker:stats", "processed", 1)
            r.hset("worker:stats", "last_ms", total)
            r.hincrby("worker:stats", "lat_sum_ms", total)
            r.hincrbyfloat("worker:stats", "proc_seconds", total / 1000.0)
            r.hincrby("worker:stats", "lat_count", 1)
            log(cid, event="completed", job_id=job_id, attempt=attempts,
                duration_ms=total, dependency="ehr+ai")
        elif verdict == "unknown":
            mark(job_id, "failed",
                 error="unknown EHR outcome: may have applied; reconcile, do not blindly retry")
            r.hincrby("worker:stats", "failed", 1)
            log(cid, event="failed", job_id=job_id, attempt=attempts,
                error="unknown-outcome-no-retry")
        elif verdict == "permanent":
            mark(job_id, "failed",
                 error=f"permanent EHR error {resp.status_code}: {body}")
            r.hincrby("worker:stats", "failed", 1)
            log(cid, event="failed", job_id=job_id, attempt=attempts,
                error="permanent")
        else:
            retry_or_fail(job_id, cid, f"temporary EHR error {resp.status_code}: {body}")
    except requests.Timeout:
        record_sync(job_id, ehr_mode(), None, int(TIMEOUT * 1000), "timeout")
        retry_or_fail(job_id, cid, f"EHR timeout after {TIMEOUT}s")
    except requests.ConnectionError:
        record_sync(job_id, "unknown", None, 0, "connection failed")
        retry_or_fail(job_id, cid, "EHR connection failed")
    except Exception as exc:  # never let one bad job kill the loop
        retry_or_fail(job_id, cid, f"worker error: {exc}")


def promote_due():
    """Move backoff-expired retries from the delay set to the live queue."""
    now = time.time()
    due = r.zrangebyscore(DELAYED, 0, now)
    if not due:
        return
    pipe = r.pipeline()
    for payload in due:
        pipe.rpush(QUEUE, payload)
        pipe.zrem(DELAYED, payload)
    pipe.execute()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 - stdlib handler naming
        if self.path == "/health":
            self._send(200, json.dumps({"status": "ok", "service": "worker",
                                        "uptime_s": int(time.time() - STARTED)}))
        elif self.path == "/ready":
            deps = {}
            try:
                r.ping()
                deps["redis"] = "up"
            except Exception:
                deps["redis"] = "down"
            try:
                conn = psycopg2.connect(DB_URL)
                conn.cursor().execute("SELECT 1")
                conn.close()
                deps["postgres"] = "up"
            except Exception:
                deps["postgres"] = "down"
            code = 200 if all(v == "up" for v in deps.values()) else 503
            self._send(code, json.dumps({"service": "worker", **deps}))
        elif self.path == "/metrics":
            stats = r.hgetall("worker:stats") or {}
            lines = [
                "# HELP jobs_processed_total jobs completed",
                "# TYPE jobs_processed_total counter",
                f"jobs_processed_total {stats.get('processed', 0)}",
                "# HELP jobs_failed_total jobs dead",
                "# TYPE jobs_failed_total counter",
                f"jobs_failed_total {stats.get('failed', 0)}",
                "# HELP jobs_retried_total retry requeues",
                "# TYPE jobs_retried_total counter",
                f"jobs_retried_total {stats.get('retried', 0)}",
                "# HELP job_last_processing_ms last completed job duration",
                "# TYPE job_last_processing_ms gauge",
                f"job_last_processing_ms {stats.get('last_ms', 0)}",
                "# HELP job_processing_ms_sum total completed-job latency",
                "# TYPE job_processing_ms_sum counter",
                f"job_processing_ms_sum {stats.get('lat_sum_ms', 0)}",
                "# HELP job_processing_count completed-job count for averages",
                "# TYPE job_processing_count counter",
                f"job_processing_count {stats.get('lat_count', 0)}",
                "# HELP worker_processing_seconds total processing time (PDF section 5)",
                "# TYPE worker_processing_seconds counter",
                f"worker_processing_seconds {stats.get('proc_seconds', 0)}",
                "# HELP queue_depth live queue length",
                "# TYPE queue_depth gauge",
                f"queue_depth {r.llen(QUEUE)}",
                "# HELP delayed_jobs backoff set size",
                "# TYPE delayed_jobs gauge",
                f"delayed_jobs {r.zcard(DELAYED)}",
                "# HELP worker_uptime_seconds process uptime",
                "# TYPE worker_uptime_seconds gauge",
                f"worker_uptime_seconds {int(time.time() - STARTED)}",
                "# HELP worker_restarts_total process starts (Redis-backed)",
                "# TYPE worker_restarts_total counter",
                f"worker_restarts_total {r.get('worker:restarts') or 0}",
            ]
            self._send(200, "\n".join(lines) + "\n",
                       ctype="text/plain; version=0.0.4")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *args):  # quiet: structured logs only
        pass


def serve_metrics():
    HTTPServer(("0.0.0.0", METRICS_PORT), Handler).serve_forever()


def main():
    r.hsetnx("worker:stats", "processed", 0)
    r.hsetnx("worker:stats", "failed", 0)
    r.hsetnx("worker:stats", "retried", 0)
    r.incr("worker:restarts")
    r.set("worker:started_at", STARTED)
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    threading.Thread(target=serve_metrics, daemon=True).start()
    heartbeat()
    last_hb = time.time()
    log(event="started", timeout_s=TIMEOUT, max_attempts=MAX_ATTEMPTS,
        metrics_port=METRICS_PORT)
    while not DRAINING:
        promote_due()
        item = r.brpoplpush(QUEUE, PROCESSING, timeout=2)
        if item:
            try:
                try:
                    handle(item)
                except Exception as exc:
                    # F4: DB down (or any infra blip) must NOT kill the loop.
                    # Park the item back on the queue, log, back off, stay alive.
                    cid = "none"
                    try:
                        cid = json.loads(item).get("correlation_id", "none")
                    except Exception:
                        pass
                    log(cid, event="loop_error", error=str(exc)[:200])
                    r.rpush(QUEUE, item)
                    time.sleep(5)
            finally:
                r.lrem(PROCESSING, 1, item)
        if time.time() - last_hb >= HB_EVERY:
            heartbeat()
            last_hb = time.time()
    log(event="shutdown", uptime_s=int(time.time() - STARTED))


if __name__ == "__main__":
    main()
