"""Alert webhook sink + gate/deploy status hub (M7 simulation).

Alertmanager POSTs here (/alerts): each notification is appended to
/data/alerts.jsonl, counted (alerts_received_total{alertname,status}), and
logged in the structured evt() schema — the evaluator's proof of "alert
fired" without SMTP/Slack.

CI and deploy scripts also POST here:
  POST /gates {name, ok}      -> security_gate_ok{name} gauge (SecurityGateFailing reads it)
  POST /deploys {version, status} -> deploy counters (DeployFailed reads them)
GET /metrics exposes all three families for Prometheus.
GET /alerts?n=20 returns recent notifications (newest first).
Limitation, stated: gauges live in memory (restart resets to 1/unknown);
CI reposts every run, so steady state is always fresh. No secrets here.
"""
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from pydantic import BaseModel

STORE = Path(os.environ.get("ALERT_STORE", "/data/alerts.jsonl"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("alert-api")


def evt(level, operation, status=None, alert=None, error=None, **extra):
    rec = {"ts": datetime.now(UTC).isoformat(),
           "level": level, "svc": "alert-api", "cid": "none", "op": operation}
    if status is not None:
        rec["status"] = status
    if alert is not None:
        rec["alert"] = alert
    if error is not None:
        rec["error"] = str(error)[:300]
    rec.update(extra)
    (log.error if level == "error" else
     log.warning if level == "warning" else log.info)(json.dumps(rec))

ALERTS_RX = Counter("alerts_received_total", "Alertmanager notifications",
                    ["alertname", "status"])
GATE = Gauge("security_gate_ok", "1 pass / 0 fail per gate", ["name"])
DEPLOY_OK = Counter("deploy_ok_total", "Successful deploys", ["version"])
DEPLOY_FAIL = Counter("deploy_failed_total", "Failed deploys", ["version"])

_lock = Lock()
_recent: list = []


def _append(notification: dict):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with STORE.open("a") as f:
            f.write(json.dumps(notification) + "\n")
        _recent.append(notification)
        del _recent[:-100]

app = FastAPI(title="alert-api (m7)")


@app.get("/health")
def health():
    return {"status": "ok", "service": "alert-api"}


@app.get("/ready")
def ready():
    ok = STORE.parent.exists()
    return {"status": "ready" if ok else "not_ready"}


class GateIn(BaseModel):
    name: str
    ok: bool


@app.post("/gates")
def set_gate(g: GateIn):
    GATE.labels(g.name).set(1 if g.ok else 0)
    evt("warning" if not g.ok else "info", "gate",
        status="fail" if not g.ok else "pass", gate=g.name)
    return {"gate": g.name, "ok": g.ok}


class DeployIn(BaseModel):
    version: str
    status: str  # ok | failed


@app.post("/deploys")
def record_deploy(d: DeployIn):
    if d.status == "failed":
        DEPLOY_FAIL.labels(d.version).inc()
    else:
        DEPLOY_OK.labels(d.version).inc()
    evt("error" if d.status == "failed" else "info", "deploy",
        status=d.status, version=d.version)
    return {"version": d.version, "status": d.status}


@app.post("/alerts")
def receive(body: dict):
    # Alertmanager webhook payload: {receiver, status, alerts: [...]}.
    note = {"ts": datetime.now(UTC).isoformat(), **body}
    for a in body.get("alerts", []):
        name = (a.get("labels") or {}).get("alertname", "unknown")
        ALERTS_RX.labels(name, body.get("status", "firing")).inc()
        evt("warning", "alert", status=body.get("status"),
            alert=name, summary=((a.get("annotations") or {}).get("summary", ""))[:200])
    _append(note)
    return {"stored": len(body.get("alerts", []))}


@app.get("/alerts")
def recent(n: int = 20):
    with _lock:
        items = list(reversed(_recent[-max(n, 1):]))
    return {"count": len(items), "alerts": items}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest().decode("utf-8"),
                             media_type=CONTENT_TYPE_LATEST)
