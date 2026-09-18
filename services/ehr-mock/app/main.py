"""Mock external EHR (M2 simulation). Failure vocabulary matches the brief:

  normal         -> fast 200, outcome=applied
  slow           -> 200 after EHR_SLOW_SLEEP_SEC (worker succeeds, slowly)
  timeout        -> sleeps EHR_TIMEOUT_SLEEP_SEC (30s) > worker timeout (5s);
                    the hung request holds one uvicorn worker, hence --workers 2
  temp_failure   -> HTTP 500 (temporary -> bounded retries w/ backoff)
  auth_failure   -> HTTP 401 (permanent -> fail fast, never retried)
  unavailable    -> HTTP 503 (temporary -> bounded retries)
  unknown        -> HTTP 200 BUT outcome=unknown: the request MAY have applied
                    server-side while the client cannot know. The worker must
                    NOT auto-retry this (duplicate side effects) — it records
                    the job as failed with a reconciliation-required error.

Mode via EHR_MODE env or POST /mode (no restart; the failure-injection
control plane). /health = liveness (always 200 + current mode).
/ready = servability: 503 only in `unavailable` (dependency still THERE in
other modes — slow/broken is different from gone). Caller correlation id
(X-Request-ID) is echoed in every response and log line.
Full connection-refused is a different drill: `docker compose stop ehr-mock`.
"""
import json
import logging
import os
import time
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel

MODES = ["normal", "slow", "timeout", "temp_failure", "auth_failure",
         "unavailable", "unknown"]
MODE = os.environ.get("EHR_MODE", "normal")
SLOW = float(os.environ.get("EHR_SLOW_SLEEP_SEC", "3"))
TIMEOUT_SLEEP = float(os.environ.get("EHR_TIMEOUT_SLEEP_SEC", "30"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ehr")


def evt(level, operation, cid="none", job_id=None, status=None,
        duration_ms=None, dependency=None, error=None, **extra):
    """Structured log event (M6): timestamp/level/service always present."""
    rec = {"ts": datetime.now(UTC).isoformat(),
           "level": level, "svc": "ehr", "cid": cid, "op": operation,
           "event": operation}
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
    rec.update(extra)
    (log.error if level == "error" else
     log.warning if level == "warning" else log.info)(json.dumps(rec))


def outcome_for(mode):
    """Pure mode->outcome mapping (unit-tested, M6). Returns
    (http_status, synced, outcome): the contract the worker classifies on."""
    table = {
        "normal": (200, True, "applied"),
        "slow": (200, True, "applied"),
        "timeout": (200, True, "applied"),
        "temp_failure": (500, False, "failed"),
        "auth_failure": (401, False, "rejected"),
        "unavailable": (503, False, "failed"),
        "unknown": (200, None, "unknown"),
    }
    return table[mode]


EHR_REQ = Counter("ehr_sync_requests_total", "sync calls", ["mode", "status"])
EHR_FAIL = Counter("ehr_sync_failures_total", "non-200 syncs", ["mode"])
EHR_TIMEOUTS = Counter("ehr_sync_timeouts_total", "timeout-mode syncs served")
EHR_LAT = Histogram("ehr_sync_duration_seconds", "sync latency", ["mode"])
EHR_MODE_OK = Gauge("ehr_mode_ok", "1 when mode serves normally")
EHR_MODE_OK.set(1)

app = FastAPI(title="ehr-mock (m6)")


@app.middleware("http")
async def _ctx(request: Request, call_next):
    # Same duplicated shape as api/ai (independent deploys).
    cid = request.headers.get("x-request-id") or "none"
    t0 = time.time()
    resp = await call_next(request)
    dt = int((time.time() - t0) * 1000)
    evt("info" if resp.status_code < 500 else "error", "http", cid=cid,
        status=resp.status_code, duration_ms=dt,
        method=request.method, path=request.url.path)
    resp.headers["X-Request-ID"] = cid
    return resp


@app.get("/health")
def health():
    return {"status": "ok", "service": "ehr", "mode": MODE}


@app.get("/ready")
def ready():
    if MODE == "unavailable":
        return JSONResponse(status_code=503,
                            content={"status": "not_ready", "mode": MODE})
    return {"status": "ready", "mode": MODE}


@app.get("/mode")
def get_mode():
    return {"mode": MODE}


class ModeIn(BaseModel):
    mode: str


@app.post("/mode")
def set_mode(m: ModeIn):
    global MODE
    if m.mode not in MODES:
        raise HTTPException(status_code=400,
                            detail=f"unknown mode, choose from {MODES}")
    MODE = m.mode
    EHR_MODE_OK.set(1 if m.mode in ("normal", "slow") else 0)
    evt("warning", "mode_change", status=200, mode=MODE,
        error=None if MODE == "normal" else "failure injection active")
    return {"mode": MODE}


@app.post("/admin/mode")
def set_mode_admin(m: ModeIn):
    # PDF §4.5 alias: same control plane, admin-prefixed path.
    return set_mode(m)


class SyncIn(BaseModel):
    job_id: int = 0
    patient_id: int | None = None


@app.post("/sync")
def sync(s: SyncIn, request: Request):
    cid = request.headers.get("x-request-id") or "none"
    t0 = time.time()
    ms = lambda: int((time.time() - t0) * 1000)  # noqa: E731
    base = {"mode": MODE, "job_id": s.job_id, "correlation_id": cid}
    status, synced, outcome = outcome_for(MODE)
    EHR_REQ.labels(MODE, str(status)).inc()
    if status != 200:
        EHR_FAIL.labels(MODE).inc()
    if MODE == "normal":
        EHR_LAT.labels(MODE).observe(time.time() - t0)
        evt("info", "sync", cid=cid, job_id=s.job_id, status=200,
            duration_ms=ms(), outcome=outcome)
        return {"synced": True, "outcome": "applied",
                "latency_ms": ms(), **base}
    if MODE == "slow":
        time.sleep(SLOW)
        EHR_LAT.labels(MODE).observe(time.time() - t0)
        evt("warning", "sync", cid=cid, job_id=s.job_id, status=200,
            duration_ms=ms(), outcome=outcome, note="slow EHR response")
        return {"synced": True, "outcome": "applied",
                "latency_ms": ms(), "note": "slow EHR response", **base}
    if MODE == "timeout":
        EHR_TIMEOUTS.inc()
        evt("warning", "sync", cid=cid, job_id=s.job_id,
            duration_ms=int(TIMEOUT_SLEEP * 1000), outcome=outcome,
            note="hanging past worker timeout")
        time.sleep(TIMEOUT_SLEEP)
        return {"synced": True, "outcome": "applied", **base}
    if MODE == "temp_failure":
        evt("error", "sync", cid=cid, job_id=s.job_id, status=500,
            duration_ms=ms(), outcome=outcome, error="EHR internal error")
        return JSONResponse(status_code=500,
                            content={"synced": False, "outcome": "failed",
                                     "error": "EHR internal error", **base})
    if MODE == "auth_failure":
        evt("warning", "sync", cid=cid, job_id=s.job_id, status=401,
            duration_ms=ms(), outcome=outcome, error="EHR auth failed")
        return JSONResponse(status_code=401,
                            content={"synced": False, "outcome": "rejected",
                                     "error": "EHR auth failed", **base})
    if MODE == "unavailable":
        evt("error", "sync", cid=cid, job_id=s.job_id, status=503,
            duration_ms=ms(), outcome=outcome, error="EHR unavailable")
        return JSONResponse(status_code=503,
                            content={"synced": False, "outcome": "failed",
                                     "error": "EHR unavailable", **base})
    # unknown: HTTP success, ambiguous result. Deliberately NOT an error code:
    # the whole point is the client cannot tell applied from failed.
    evt("error", "sync", cid=cid, job_id=s.job_id, status=200,
        duration_ms=ms(), outcome=outcome,
        error="outcome unknown: may have applied; reconcile")
    return {"synced": None, "outcome": "unknown",
            "error": "outcome unknown: request may have applied; reconcile, do not blindly retry",
            "latency_ms": ms(), **base}


@app.post("/ehr/sync")
def sync_ehr(s: SyncIn, request: Request):
    # PDF §4.5 alias: namespaced path, same handler and contract.
    return sync(s, request)


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest().decode("utf-8"),
                             media_type=CONTENT_TYPE_LATEST)
