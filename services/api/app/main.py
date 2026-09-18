"""Patient/API service (M2 simulation).

Owns: synthetic registry (hospitals/doctors/patients/appointments), versioned
job intake (/api/v1/*), job status reads, worker-liveness view, Prometheus
metrics. Correlation: every request gets X-Request-ID (client-supplied or
generated); POST /api/v1/jobs mints the job correlation id from it, and the
id travels in the Redis envelope to worker -> AI/EHR.
POST /api/v1/appointments enriches via AI /process with graceful fallback:
AI down/slow => appointment still created, risk=null, degraded=true.
Readiness reports only UP/DOWN per dependency (never exception text: no
credential or internal-detail leakage); full errors go to server logs.
"""
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime

import psycopg2
import psycopg2.extras
import redis
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, Info, generate_latest
from pydantic import BaseModel, Field

VERSION = os.environ.get("API_VERSION", "m6")
DB_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
AI_URL = os.environ.get("AI_URL", "http://ai:8001")
AI_TIMEOUT = float(os.environ.get("AI_TIMEOUT_SEC", "3"))
QUEUE = "jobs:queue"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("api")


def evt(level, operation, cid="none", job_id=None, status=None,
        duration_ms=None, dependency=None, error=None, **extra):
    """Structured log event (M6). Every line carries timestamp/level/service;
    correlation + job + operation + status + duration + dependency + error
    when applicable. Single schema an operator can grep and join on."""
    rec = {"ts": datetime.now(UTC).isoformat(),
           "level": level, "svc": "api", "version": VERSION,
           "cid": cid, "op": operation, "event": operation}
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

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

HTTP_REQ = Counter("api_http_requests_total", "HTTP requests handled",
                   ["method", "path", "status"])
HTTP_LAT = Histogram("api_http_request_duration_seconds", "HTTP request latency",
                     ["path"])
HTTP_ACTIVE = Gauge("api_http_active_requests", "Requests currently in flight")
JOBS_ENQ = Counter("api_jobs_enqueued_total", "Jobs accepted via POST /api/v1/jobs")
DB_ERR = Counter("api_db_errors_total", "Postgres failures by operation",
                 ["op"])
BUILD = Info("api_build", "Deployment version info")
BUILD.info({"version": VERSION})

app = FastAPI(title="healthcare-api (m6)")


@app.middleware("http")
async def _context(request: Request, call_next):
    cid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.cid = cid
    t0 = time.time()
    HTTP_ACTIVE.inc()
    try:
        try:
            resp = await call_next(request)
            status = resp.status_code
        except Exception as exc:
            evt("error", "http", cid=cid, status=500,
                duration_ms=int((time.time() - t0) * 1000),
                method=request.method, path=request.url.path, error=exc)
            raise
        dt_ms = int((time.time() - t0) * 1000)
        if request.url.path != "/metrics":
            HTTP_REQ.labels(request.method, request.url.path, str(status)).inc()
            HTTP_LAT.labels(request.url.path).observe(dt_ms / 1000.0)
        evt("info" if status < 500 else "error", "http", cid=cid, status=status,
            duration_ms=dt_ms, method=request.method, path=request.url.path)
        resp.headers["X-Request-ID"] = cid
        return resp
    finally:
        HTTP_ACTIVE.dec()


def pg():
    return psycopg2.connect(DB_URL)


def build_envelope(job_id: int, correlation_id: str, job_type: str) -> dict:
    """Pure constructor for the Redis job envelope (unit-tested).

    Format: job_id (DB primary key, authoritative), correlation_id
    (end-to-end trace), type (routing hint), enqueued_at (epoch, for
    queue-latency math). Attempts live in Postgres, not here.
    """
    return {"job_id": job_id, "correlation_id": correlation_id,
            "type": job_type, "enqueued_at": time.time()}


@app.get("/health")
def health():
    return {"status": "ok", "service": "api", "version": VERSION}


@app.get("/version")
def version():
    # PDF §4.1 alias: same release identity as /health + api_build_info.
    return {"service": "api", "version": VERSION}


@app.get("/ready")
def ready(request: Request):
    # BREAK_READY=1 is the deployment-failure injector (M11): same philosophy
    # as EHR_MODE — a broken release must FAIL READINESS so the deploy gate
    # blocks it. Read per-request (not import-time) so tests can flip it.
    if os.environ.get("BREAK_READY") == "1":
        evt("warning", "ready", cid=request.state.cid, status="not_ready",
            error="BREAK_READY injector active")
        return JSONResponse(status_code=503,
                            content={"status": "not_ready", "broken": "BREAK_READY"})
    deps = {}
    try:
        conn = pg()
        conn.cursor().execute("SELECT 1")
        conn.close()
        deps["postgres"] = "up"
    except Exception as exc:
        DB_ERR.labels("ready").inc()
        evt("warning", "ready", cid=request.state.cid, dependency="postgres",
            status="down", error=exc)
        deps["postgres"] = "down"
    try:
        r.ping()
        deps["redis"] = "up"
    except Exception as exc:
        evt("warning", "ready", cid=request.state.cid, dependency="redis",
            status="down", error=exc)
        deps["redis"] = "down"
    if all(v == "up" for v in deps.values()):
        return {"status": "ready", **deps}
    return JSONResponse(status_code=503, content={"status": "not_ready", **deps})


class JobIn(BaseModel):
    type: str = "appointment"
    patient_id: int | None = None
    payload: dict = Field(default_factory=dict)


@app.post("/api/v1/jobs", status_code=201)
def create_job(job: JobIn, request: Request):
    cid = request.state.cid
    conn = pg()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO jobs(type, patient_id, payload, correlation_id)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (job.type, job.patient_id, json.dumps(job.payload), cid),
        )
        job_id = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    # Durable intent (DB row) first, queue signal second.
    r.rpush(QUEUE, json.dumps(build_envelope(job_id, cid, job.type)))
    JOBS_ENQ.inc()
    return {"job_id": job_id, "correlation_id": cid, "status": "queued"}


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: int):
    conn = pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    return dict(row)


@app.get("/api/v1/patients")
def list_patients():
    conn = pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, first_name, last_name, dob FROM patients ORDER BY id")
        rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(x) for x in rows]


class PatientIn(BaseModel):
    first_name: str
    last_name: str
    dob: str  # YYYY-MM-DD


@app.get("/api/v1/patients/{patient_id}")
def get_patient(patient_id: int):
    conn = pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, first_name, last_name, dob FROM patients WHERE id = %s",
                    (patient_id,))
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="patient not found")
    return dict(row)


@app.post("/api/v1/patients", status_code=201)
def create_patient(p: PatientIn):
    conn = pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO patients(first_name, last_name, dob) VALUES (%s, %s, %s) RETURNING id",
            (p.first_name, p.last_name, p.dob),
        )
        pid = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return {"id": pid}


@app.get("/api/v1/doctors")
def list_doctors():
    conn = pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, first_name, last_name, specialty, hospital_id"
                    " FROM doctors ORDER BY id")
        rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(x) for x in rows]


@app.get("/api/v1/hospitals")
def list_hospitals():
    conn = pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name, city FROM hospitals ORDER BY id")
        rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(x) for x in rows]


@app.get("/api/v1/appointments")
def list_appointments():
    conn = pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, patient_id, doctor_id, scheduled_at, status"
                    " FROM appointments ORDER BY id")
        rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(x) for x in rows]


class ApptIn(BaseModel):
    patient_id: int
    doctor_id: int
    scheduled_at: str  # ISO datetime


@app.post("/api/v1/appointments", status_code=201)
def create_appointment(a: ApptIn, request: Request):
    cid = request.state.cid
    # Ask AI for a risk flag where appropriate; degrade gracefully —
    # an AI outage must not block appointment booking.
    risk, degraded = None, False
    t0 = time.time()
    try:
        resp = requests.post(f"{AI_URL}/process",
                             json={"text": f"appointment p{a.patient_id} d{a.doctor_id}"},
                             headers={"X-Request-ID": cid}, timeout=AI_TIMEOUT)
        dt = int((time.time() - t0) * 1000)
        if resp.status_code == 200:
            risk = resp.json().get("label")
            evt("info", "ai_enrich", cid=cid, dependency="ai",
                status=200, duration_ms=dt)
        else:
            degraded = True
            evt("warning", "ai_enrich", cid=cid, dependency="ai",
                status=resp.status_code, duration_ms=dt, error="non-200, degraded")
    except Exception as exc:
        degraded = True
        evt("warning", "ai_enrich", cid=cid, dependency="ai",
            duration_ms=int((time.time() - t0) * 1000), error=exc)
    conn = pg()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO appointments(patient_id, doctor_id, scheduled_at)
               VALUES (%s, %s, %s) RETURNING id""",
            (a.patient_id, a.doctor_id, a.scheduled_at),
        )
        aid = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return {"id": aid, "risk": risk, "ai_degraded": degraded}


@app.get("/worker/status")
def worker_status():
    # Worker serves its own :8003 too (M2); this view stays as the
    # Redis-based summary (heartbeat + counters + live depths).
    hb = r.get("worker:heartbeat")
    stats = r.hgetall("worker:stats") or {}
    age = time.time() - float(hb) if hb else None
    return {
        "alive": age is not None and age < 15,
        "heartbeat_age_sec": round(age, 1) if age is not None else None,
        "processed": int(stats.get("processed", 0)),
        "failed": int(stats.get("failed", 0)),
        "retried": int(stats.get("retried", 0)),
        "restarts": int(r.get("worker:restarts") or 0),
        "queue_depth": r.llen(QUEUE),
        "delayed": r.zcard("jobs:delayed"),
    }


def queue_stats(depth, delayed, oldest_enqueued_at, now=None):
    """Pure queue math (unit-tested): counts plus oldest-job age, i.e. the
    current queue latency. The live endpoint below supplies the inputs."""
    now = now if now is not None else time.time()
    age = (now - oldest_enqueued_at) if oldest_enqueued_at else 0.0
    return {"queue_depth": depth, "delayed": delayed,
            "oldest_age_s": round(max(age, 0.0), 1)}


@app.get("/api/v1/queue/stats")
def queue_stats_live():
    depth = r.llen(QUEUE)
    delayed = r.zcard("jobs:delayed")
    ts = None
    oldest = r.lindex(QUEUE, 0)
    if oldest:
        try:
            ts = float(json.loads(oldest).get("enqueued_at"))
        except Exception:
            ts = None
    return queue_stats(depth, delayed, ts)


@app.get("/api/v1/db/stats")
def db_stats():
    # Practical DB telemetry: round-trip latency + connection pressure.
    # Graceful 503 (never a traceback) keeps this safe to poll in drills.
    try:
        t0 = time.time()
        conn = pg()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        qms = int((time.time() - t0) * 1000)
        cur.execute("SELECT count(*) FROM pg_stat_activity"
                    " WHERE datname = current_database();")
        active = cur.fetchone()[0]
        cur.execute("SHOW max_connections;")
        maxc = int(cur.fetchone()[0])
        conn.close()
    except Exception as exc:
        DB_ERR.labels("db_stats").inc()
        evt("warning", "db_stats", dependency="postgres", status="down", error=exc)
        return JSONResponse(status_code=503, content={"status": "down"})
    return {"query_ms": qms, "connections_active": active,
            "max_connections": maxc}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest().decode("utf-8"),
                             media_type=CONTENT_TYPE_LATEST)
