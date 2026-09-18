"""AI/agent mock (M2 simulation). No model, no weights, no external calls.

POST /process sleeps AI_LATENCY_SEC (simulated inference) and returns a
deterministic mock label. Failure injection mirrors the EHR pattern:
  ok          -> normal processing
  temp500     -> HTTP 500 (caller should treat as temporary)
  unavail503  -> HTTP 503 (caller should treat as temporary)
Switch at runtime via POST /mode (env AI_FAIL_MODE sets the default).
/health = liveness (always 200 while running). /ready = servability:
503 while a failure mode is active. /metrics exposes processed/failed.
/process echoes the caller's X-Request-ID for end-to-end tracing.
"""
import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel

LAT = float(os.environ.get("AI_LATENCY_SEC", "0.5"))
MODES = ["ok", "temp500", "unavail503"]
MODE = os.environ.get("AI_FAIL_MODE", "ok")
LABELS = [("low_risk", 0.91), ("needs_review", 0.66), ("urgent", 0.83)]

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ai")


def evt(level, operation, cid="none", job_id=None, status=None,
        duration_ms=None, error=None, **extra):
    """Structured log event (M6): timestamp/level/service always present."""
    rec = {"ts": datetime.now(UTC).isoformat(),
           "level": level, "svc": "ai", "cid": cid, "op": operation}
    if job_id is not None:
        rec["job_id"] = job_id
    if status is not None:
        rec["status"] = status
    if duration_ms is not None:
        rec["duration_ms"] = duration_ms
    if error is not None:
        rec["error"] = str(error)[:300]
    rec.update(extra)
    (log.error if level == "error" else
     log.warning if level == "warning" else log.info)(json.dumps(rec))

AI_REQ = Counter("ai_requests_total", "process calls", ["status"])
AI_FAIL = Counter("ai_failures_total", "injected failures", ["mode"])
AI_LAT = Histogram("ai_process_duration_seconds", "Inference latency")
AI_MODE = Gauge("ai_mode_ok", "1 when mode=ok else 0")
AI_MODE.set(1 if MODE == "ok" else 0)

app = FastAPI(title="ai-mock (m6)")


@app.middleware("http")
async def _ctx(request: Request, call_next):
    # Duplicated per service on purpose: services deploy independently,
    # so no shared library. Same shape everywhere.
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
    return {"status": "ok", "service": "ai", "mode": MODE}


@app.get("/ready")
def ready():
    if MODE != "ok":
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
    AI_MODE.set(1 if MODE == "ok" else 0)
    evt("warning", "mode_change", status=200, mode=MODE,
        error=None if MODE == "ok" else "failure injection active")
    return {"mode": MODE}


class ProcessIn(BaseModel):
    job_id: int = 0
    text: str = ""


@app.post("/process")
def process(p: ProcessIn, request: Request):
    cid = request.headers.get("x-request-id") or "none"
    if MODE == "temp500":
        AI_REQ.labels("500").inc()
        AI_FAIL.labels(MODE).inc()
        return JSONResponse(status_code=500,
                            content={"error": "AI temporary failure",
                                     "mode": MODE, "correlation_id": cid})
    if MODE == "unavail503":
        AI_REQ.labels("503").inc()
        AI_FAIL.labels(MODE).inc()
        return JSONResponse(status_code=503,
                            content={"error": "AI unavailable",
                                     "mode": MODE, "correlation_id": cid})
    t0 = time.time()
    time.sleep(LAT)  # simulated inference latency; nothing real happens here
    label, conf = LABELS[int(hashlib.sha256(str(p.job_id).encode()).hexdigest(), 16) % 3]
    dt = (time.time() - t0)
    AI_REQ.labels("200").inc()
    AI_LAT.observe(dt)
    evt("info", "process", cid=cid, job_id=p.job_id, status=200,
        duration_ms=int(dt * 1000), label=label)
    return {"job_id": p.job_id, "label": label, "confidence": conf,
            "latency_ms": int(dt * 1000),
            "mode": MODE, "correlation_id": cid}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest().decode("utf-8"),
                             media_type=CONTENT_TYPE_LATEST)
