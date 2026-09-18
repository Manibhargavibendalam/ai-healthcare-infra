"""M2 tests: foundation (no engine) + pure application logic.
Live-DB/Redis paths stay integration tests behind the stack (m1-verify.sh).
"""
import importlib.util
import subprocess
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


api = load("api_main", "services/api/app/main.py")
ai = load("ai_main", "services/ai-service/app/main.py")
ehr = load("ehr_main", "services/ehr-mock/app/main.py")
worker = load("worker_mod", "services/worker/worker.py")


# --- configuration loading ---

def test_env_example_has_only_placeholders():
    # Policy: SECRET keys must be placeholders; non-secret dev defaults ok.
    for line in (ROOT / ".env.example").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        assert key == key.upper(), f"non-upper key: {key}"
        assert value, f"empty value for {key}"
        if key.endswith(("PASSWORD", "SECRET", "TOKEN", "KEY")):
            assert value.startswith("CHANGE_ME"), f"real-looking secret for {key}"


def test_dotenv_is_gitignored():
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", ".env"])
    assert r.returncode == 0, ".env is NOT ignored — secrets could be committed"


def test_compose_structure():
    # M3 network policy as code: nginx alone on a published port, api the
    # only dual-homed service, everything else internal-only. If someone
    # exposes the DB, THIS test fails the build.
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    svcs = compose["services"]
    assert set(svcs) == {"db", "redis", "api", "ai", "ehr", "worker", "nginx", "loadgen"}
    assert set(compose["networks"]) == {"edge", "internal"}
    published = {n: s.get("ports", []) for n, s in svcs.items()}
    assert published["nginx"] == ["127.0.0.1:8080:8080"]
    for n in ("db", "redis", "api", "ai", "ehr", "worker"):
        assert published[n] == [], f"{n} publishes host ports"
    assert set(svcs["nginx"]["networks"]) == {"edge"}
    assert set(svcs["api"]["networks"]) == {"edge", "internal"}
    for n in ("db", "redis", "ai", "ehr", "worker"):
        assert svcs[n]["networks"] == ["internal"], f"{n} not internal-only"
    for n in ("api", "ai", "ehr", "worker", "nginx"):
        assert svcs[n].get("init") is True, f"{n} missing init:true"
        assert "cpus" in svcs[n] and "mem_limit" in svcs[n], f"{n} missing limits"
    assert "db/migrations" in str(svcs["db"]["volumes"]), "migrations dir not mounted"
    lg = svcs["loadgen"]
    assert lg["profiles"] == ["loadgen"], "loadgen must never autostart"
    assert lg["networks"] == ["edge"], "loadgen enters via ingress only"


def test_loadgen_files():
    assert (ROOT / "loadgen" / "locustfile.py").exists()
    assert (ROOT / "loadgen" / "Dockerfile").exists()
    req = (ROOT / "loadgen" / "requirements.txt").read_text()
    assert "locust==" in req, "loadgen dep must be pinned"
    lf = (ROOT / "loadgen" / "locustfile.py").read_text()
    for cls in ("NormalUser", "ApiHeavy", "JobPoster", "BurstUser"):
        assert cls in lf, f"{cls} workload missing"


def test_dockerfiles_pinned_and_nonroot():
    pins = {"api": "python:3.12.14-slim", "ai-service": "python:3.12.14-slim",
            "ehr-mock": "python:3.12.14-slim", "worker": "python:3.12.14-slim"}
    for svc, base in pins.items():
        content = (ROOT / "services" / svc / "Dockerfile").read_text()
        assert f"FROM {base}" in content, f"{svc} base not pinned to {base}"
        assert "USER appuser" in content, f"{svc} does not drop privileges"
        assert "PASSWORD" not in content and "SECRET" not in content
    ng = (ROOT / "nginx" / "Dockerfile").read_text()
    assert "FROM nginxinc/nginx-unprivileged:1.31.6-alpine" in ng
    assert "HEALTHCHECK" in ng and "nginx -t" in ng


def test_nginx_conf():
    conf = (ROOT / "nginx" / "nginx.conf").read_text()
    assert "listen 8080" in conf
    # Dynamic upstream (resolver), NOT a static server line: static pins one replica.
    assert "resolver 127.0.0.11" in conf
    assert "set $backend api" in conf
    assert "proxy_pass http://$backend:8000" in conf
    assert "server_tokens off" in conf
    assert "X-Request-ID" in conf, "correlation header not forwarded"
    assert "location = /healthz" in conf


def test_seed_data_is_synthetic():
    sql = (ROOT / "db" / "migrations" / "001_schema.sql").read_text()
    assert "ALL DATA BELOW IS FAKE" in sql
    assert "Test', 'Patient-" in sql
    hosp = (ROOT / "db" / "migrations" / "002_hospitals.sql").read_text()
    assert "Test General Hospital" in hosp
    assert "ON CONFLICT" in sql, "seeds must be idempotent for migrate.sh"


def test_migrations_are_ordered_and_tracked():
    migs = sorted((ROOT / "db" / "migrations").glob("*.sql"))
    assert [m.name for m in migs] == ["001_schema.sql", "002_hospitals.sql",
                                      "003_correlation.sql"]
    assert "schema_migrations" in migs[0].read_text()


# --- API service (in-process, no DB) ---

def test_api_health():
    r = TestClient(api.app).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_api_ready_reports_failure_without_crashing():
    r = TestClient(api.app).get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    # No internal details leaked: values are exactly up/down.
    assert set(body.values()) <= {"not_ready", "up", "down"}


def test_api_metrics_exposed():
    body = TestClient(api.app).get("/metrics").text
    assert "api_http_requests_total" in body
    assert "api_jobs_enqueued_total" in body
    assert "api_http_active_requests" in body
    assert "api_build_info" in body
    assert "api_db_errors_total" in body


def test_log_schema_all_services():
    # evt()/log() is the contract: ts/level/svc/cid/op always present.
    import inspect
    for mod, fn in ((api, "evt"), (ai, "evt"), (ehr, "evt"), (worker, "log")):
        src = inspect.getsource(getattr(mod, fn))
        for key in ('"ts"', '"level"', '"svc"', '"cid"', '"op"'):
            assert key in src, f"{mod.__name__}.{fn}() missing {key}"


def test_api_request_id_echoed():
    c = TestClient(api.app)
    r = c.get("/health", headers={"X-Request-ID": "trace-123"})
    assert r.headers["x-request-id"] == "trace-123"
    assert len(c.get("/health").headers["x-request-id"]) == 12  # generated


def test_job_envelope_shape():
    env = api.build_envelope(42, "cid-abc", "appointment")
    assert env == {"job_id": 42, "correlation_id": "cid-abc",
                   "type": "appointment", "enqueued_at": env["enqueued_at"]}
    assert isinstance(env["enqueued_at"], float)


# NOTE: the AI-degraded appointment path needs Postgres, so it is a LIVE
# test (m1-verify.sh T10), not a unit test: without a DB the endpoint
# cannot reach the INSERT, with or without AI.


# --- EHR mock: full failure vocabulary ---

def test_ehr_mode_cycle():
    c = TestClient(ehr.app)
    try:
        assert c.get("/mode").json() == {"mode": "normal"}
        assert c.post("/mode", json={"mode": "nope"}).status_code == 400
        for m in ["slow", "timeout", "temp_failure", "auth_failure",
                  "unavailable", "unknown"]:
            assert c.post("/mode", json={"mode": m}).json() == {"mode": m}
        assert c.get("/health").json()["mode"] == "unknown"
    finally:
        ehr.MODE = "normal"


def test_ehr_ready_only_fails_when_gone():
    c = TestClient(ehr.app)
    try:
        assert c.get("/ready").status_code == 200
        c.post("/mode", json={"mode": "temp_failure"})
        assert c.get("/ready").status_code == 200  # broken != gone
        c.post("/mode", json={"mode": "unavailable"})
        assert c.get("/ready").status_code == 503
    finally:
        ehr.MODE = "normal"


def test_ehr_sync_matrix():
    c = TestClient(ehr.app)
    try:
        c.post("/mode", json={"mode": "normal"})
        ok = c.post("/sync", json={"job_id": 1}).json()
        assert ok["synced"] is True and ok["outcome"] == "applied"
        c.post("/mode", json={"mode": "temp_failure"})
        assert c.post("/sync", json={"job_id": 1}).status_code == 500
        c.post("/mode", json={"mode": "auth_failure"})
        assert c.post("/sync", json={"job_id": 1}).status_code == 401
        c.post("/mode", json={"mode": "unavailable"})
        assert c.post("/sync", json={"job_id": 1}).status_code == 503
    finally:
        ehr.MODE = "normal"


def test_ehr_unknown_outcome():
    c = TestClient(ehr.app)
    try:
        c.post("/mode", json={"mode": "unknown"})
        r = c.post("/sync", json={"job_id": 9},
                   headers={"X-Request-ID": "cid-9"})
        assert r.status_code == 200  # the trap: success code, ambiguous result
        body = r.json()
        assert body["outcome"] == "unknown" and body["synced"] is None
        assert body["correlation_id"] == "cid-9"
    finally:
        ehr.MODE = "normal"


# --- AI mock ---

def test_ai_health_ready_metrics():
    c = TestClient(ai.app)
    assert c.get("/health").json()["status"] == "ok"
    assert c.get("/ready").status_code == 200
    body = c.get("/metrics").text
    assert "ai_requests_total" in body
    assert "ai_process_duration_seconds" in body
    assert "ai_mode_ok" in body


def test_ai_process_and_modes():
    c = TestClient(ai.app)
    try:
        body = c.post("/process", json={"job_id": 7}).json()
        assert body["label"] in {"low_risk", "needs_review", "urgent"}
        c.post("/mode", json={"mode": "temp500"})
        assert c.post("/process", json={"job_id": 7}).status_code == 500
        assert c.get("/ready").status_code == 503
        c.post("/mode", json={"mode": "unavail503"})
        assert c.post("/process", json={"job_id": 7}).status_code == 503
    finally:
        ai.MODE = "ok"


def test_ehr_outcome_matrix():
    assert ehr.outcome_for("normal") == (200, True, "applied")
    assert ehr.outcome_for("slow") == (200, True, "applied")
    assert ehr.outcome_for("timeout") == (200, True, "applied")
    assert ehr.outcome_for("temp_failure") == (500, False, "failed")
    assert ehr.outcome_for("auth_failure") == (401, False, "rejected")
    assert ehr.outcome_for("unavailable") == (503, False, "failed")
    assert ehr.outcome_for("unknown") == (200, None, "unknown")


def test_ehr_metrics_exposed():
    body = TestClient(ehr.app).get("/metrics").text
    for m in ("ehr_sync_requests_total", "ehr_sync_failures_total",
              "ehr_sync_timeouts_total", "ehr_sync_duration_seconds",
              "ehr_mode_ok"):
        assert m in body, f"EHR metric {m} missing"


def test_worker_metrics_schema():
    import inspect
    src = inspect.getsource(worker.Handler.do_GET)
    for m in ("job_processing_ms_sum", "job_processing_count",
              "jobs_processed_total", "jobs_failed_total", "jobs_retried_total",
              "queue_depth", "delayed_jobs", "worker_uptime_seconds",
              "worker_restarts_total", "job_last_processing_ms"):
        assert m in src, f"worker metric {m} missing"


def test_prometheus_scrapes_everything():
    prom = yaml.safe_load((ROOT / "monitoring" / "prometheus" / "prometheus.yml").read_text())
    jobs = {s["job_name"] for s in prom["scrape_configs"]}
    assert {"api", "ai", "ehr", "worker", "postgres", "node", "prometheus"} <= jobs


def test_monitoring_overlay():
    mon = yaml.safe_load((ROOT / "compose.monitoring.yaml").read_text())
    svcs = mon["services"]
    assert set(svcs) >= {"prometheus", "grafana", "postgres-exporter", "node-exporter"}
    assert svcs["prometheus"]["ports"] == ["127.0.0.1:9090:9090"]
    assert svcs["grafana"]["ports"] == ["127.0.0.1:3000:3000"]
    assert "ports" not in svcs["postgres-exporter"], "exporter must not publish ports"
    assert "ports" not in svcs["node-exporter"], "exporter must not publish ports"
    for n in svcs.values():
        assert n["networks"] == ["internal"], "monitoring stays internal-only"
    mon_text = (ROOT / "compose.monitoring.yaml").read_text().replace(" ", "")
    assert "prom/prometheus:v3.14.0" in mon_text
    assert "grafana/grafana:11.6.16" in mon_text


def test_dashboard_answers_fifteen_questions():
    import json as _json
    dash_path = ROOT / "monitoring" / "grafana" / "dashboards" / "healthcare.json"
    dash = _json.loads(dash_path.read_text())
    titles = [p["title"] for p in dash["panels"]]
    assert len(dash["panels"]) == 15, f"want 15 panels, got {len(titles)}"
    for q in ("API healthy", "Request rate", "Error rate", "Latency",
              "processing", "Queue depth", "restarts", "PostgreSQL",
              "EHR", "Deployment", "Saturation", "Worker healthy",
              "Failed", "EHR latency", "availability"):
        assert any(q.lower() in t.lower() for t in titles), f"no panel for {q}"


def test_alert_rules_ten_with_contract():
    rules = yaml.safe_load((ROOT / "monitoring" / "prometheus" / "alert.rules.yml").read_text())
    found = [r["alert"] for g in rules["groups"] for r in g["rules"]]
    expected = ["ApiDown", "ApiHighErrorRate", "ApiHighLatency", "WorkerDown",
                "QueueBacklog", "PostgresDown", "DeployFailed", "NodeSaturation",
                "SecurityGateFailing", "EhrFailing"]
    assert sorted(found) == sorted(expected), f"rules: {found}"
    for g in rules["groups"]:
        for r in g["rules"]:
            assert r.get("expr"), f"{r['alert']} has no expr"
            assert r.get("for"), f"{r['alert']} has no for (flap guard required)"
            assert r["labels"].get("severity") in ("critical", "warning"), r["alert"]
            for a in ("summary", "description", "cause", "action", "verify"):
                assert r["annotations"].get(a), f"{r['alert']} missing annotation {a}"


def test_alert_rules_reference_real_metrics():
    text = (ROOT / "monitoring" / "prometheus" / "alert.rules.yml").read_text()
    for m in ("up{job=\"api\"}", "api_http_requests_total",
              "api_http_request_duration_seconds_bucket", "up{job=\"worker\"}",
              "queue_depth", "pg_up", "deploy_failed_total",
              "node_cpu_seconds_total", "security_gate_ok",
              "ehr_sync_failures_total", "ehr_mode_ok"):
        assert m in text, f"rule references unknown metric {m}"


def test_alertmanager_config():
    am = yaml.safe_load((ROOT / "monitoring" / "alertmanager" / "alertmanager.yml").read_text())
    assert am["route"]["receiver"] == "webhook"
    assert am["route"]["group_wait"] == "30s"
    assert am["route"]["repeat_interval"] == "4h"
    recv = {r["name"]: r for r in am["receivers"]}
    urls = str(recv["webhook"])
    assert "http://alert-api:8080/alerts" in urls


def test_monitoring_overlay_alerts():
    mon = yaml.safe_load((ROOT / "compose.monitoring.yaml").read_text())
    svcs = mon["services"]
    assert set(svcs) >= {"prometheus", "grafana", "postgres-exporter",
                         "node-exporter", "alertmanager", "alert-api"}
    assert "ports" not in svcs["alertmanager"], "alertmanager must not publish ports"
    assert "ports" not in svcs["alert-api"], "alert-api must not publish ports"
    assert svcs["alertmanager"]["networks"] == ["internal"]
    assert svcs["alert-api"]["networks"] == ["internal"]
    prom = svcs["prometheus"]
    vols = " ".join(str(v) for v in prom["volumes"])
    assert "alert.rules.yml" in vols, "rules file not mounted into prometheus"
    deps = str(prom.get("depends_on", {}))
    assert "alertmanager" in deps, "prometheus must wait for alertmanager"
    mon_text = (ROOT / "compose.monitoring.yaml").read_text().replace(" ", "")
    assert "prom/alertmanager:v0.34.1" in mon_text


def test_alert_api_files():
    dockerfile = (ROOT / "services" / "alert-api" / "Dockerfile").read_text()
    assert "FROM python:3.12.14-slim" in dockerfile
    assert "USER appuser" in dockerfile
    req = (ROOT / "services" / "alert-api" / "requirements.txt").read_text()
    assert "fastapi==" in req and "prometheus_client==" in req
    src = (ROOT / "services" / "alert-api" / "app" / "main.py").read_text()
    for ep in ('@app.post("/alerts")', '@app.get("/alerts")',
               '@app.post("/gates")', '@app.post("/deploys")',
               '@app.get("/metrics")', "security_gate_ok",
               "deploy_failed_total", "alerts_received_total"):
        assert ep in src, f"alert-api missing {ep}"


def test_deploy_overlay_candidate():
    cand = yaml.safe_load((ROOT / "compose.candidate.yaml").read_text())
    svc = cand["services"]["api-candidate"]
    assert svc["image"] == "healthcare-api:${API_TAG:?API_TAG must be set by deploy.sh}"
    assert svc["networks"] == ["internal"], "candidate must be internal-only"
    assert "ports" not in svc, "candidate must publish no ports"
    assert svc.get("restart") == "no", "candidate must not self-heal into looking healthy"
    assert "build" not in svc, "candidate runs the prebuilt tag, never rebuilds"
    assert "./scripts:/scripts:ro" in svc["volumes"]
    assert "8000/health" in " ".join(svc["healthcheck"]["test"])


def test_api_image_versioned():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    assert compose["services"]["api"]["image"] == "healthcare-api:${API_TAG:-dev}"


def test_deploy_script_gates_before_switch():
    src = (ROOT / "scripts" / "deploy.sh").read_text()
    gate = src.index("candidate_ready")
    switch = src.index("up -d --no-deps api")
    assert gate < switch, "readiness gate must precede the traffic switch"
    assert "post_deploy failed" in src and "exit 1" in src
    assert "post_deploy ok" in src
    assert "deployments.jsonl" in src
    for ep in ("/deploys", "api-candidate", "8080/ready"):
        assert ep in src, f"deploy.sh missing {ep}"


def test_rollback_refuses_without_history():
    src = (ROOT / "scripts" / "rollback.sh").read_text()
    assert "deployments.jsonl" in src
    assert "ROLLBACK REFUSED" in src
    assert "exit 1" in src
    assert "/deploys" in src, "rollback must record itself as a deploy"


def test_ci_calls_deploy_and_scans_right_image():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "bash scripts/deploy.sh" in ci
    assert "healthcare-api:ci" in ci
    assert "API_TAG=ci docker compose build" in ci
    assert "ai-healthcare-infra-m1-api" not in ci, "stale image ref"


def test_alert_api_has_scripts_mount():
    mon = yaml.safe_load((ROOT / "compose.monitoring.yaml").read_text())
    vols = " ".join(str(v) for v in mon["services"]["alert-api"]["volumes"])
    assert "./scripts:/scripts:ro" in vols, "deploy posts need the svc.py channel"


def test_terraform_layout():
    mods = ROOT / "terraform" / "modules"
    assert sorted(p.name for p in mods.iterdir() if p.is_dir()) == [
        "compute", "database", "monitoring", "network", "queue", "security"]
    for m in ("compute", "database", "monitoring", "network", "queue", "security"):
        for f in ("main.tf", "variables.tf", "outputs.tf"):
            assert (mods / m / f).exists(), f"modules/{m}/{f} missing"
    assert not (mods / "app").exists(), "stale app module still present"
    assert not (mods / "data").exists(), "stale data module still present"
    for env in ("dev", "prod"):
        main = (ROOT / "terraform" / "environments" / env / "main.tf").read_text()
        for m in ("network", "security", "database", "queue", "monitoring", "compute"):
            assert f'module "{m}"' in main, f"{env} does not wire module {m}"


def test_terraform_no_hardcoded_secrets():
    import re
    hits = []
    for tf in (ROOT / "terraform").rglob("*.tf"):
        if ".terraform" in tf.parts:
            continue
        for i, line in enumerate(tf.read_text().splitlines(), 1):
            if re.search(r'(?i)(password|secret|token)\s*=\s*"[^"$]+\"', line):
                hits.append(f"{tf.name}:{i}")
    assert not hits, f"literal secrets in terraform: {hits}"


def _all_overlays():
    base = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]
    mon = yaml.safe_load((ROOT / "compose.monitoring.yaml").read_text())["services"]
    cand = yaml.safe_load((ROOT / "compose.candidate.yaml").read_text())["services"]
    return base, mon, cand


def test_container_hardening():
    # M9: read-only + dropped caps everywhere practical; no privileged ever.
    # Stateful/complex exceptions (db/redis/prometheus/grafana) are an
    # EXPLICIT list — adding a new writable service without justification
    # fails this test.
    base, mon, cand = _all_overlays()
    ro_expected = {"api", "ai", "ehr", "worker", "nginx", "loadgen",
                   "alert-api", "alertmanager", "postgres-exporter",
                   "node-exporter", "api-candidate"}
    ro_exception = {"db", "redis", "prometheus", "grafana"}  # see SECURITY.md
    all_svcs = {**base, **mon, **cand}
    for name, svc in all_svcs.items():
        assert svc.get("privileged") is not True, f"{name} is privileged"
        assert svc.get("cap_drop") == ["ALL"], f"{name} keeps Linux caps"
    for name in ro_expected:
        assert all_svcs[name].get("read_only") is True, f"{name} not read-only"
        assert "/tmp" in str(all_svcs[name].get("tmpfs", [])), f"{name} lacks /tmp tmpfs"
    for name in ro_exception:
        assert all_svcs[name].get("read_only") is not True, \
            f"{name} must stay in the documented exception list, not silently harden"


def test_no_secrets_in_compose_or_ci():
    # M9: secret VALUES never appear in compose/CI/TF-adjacent YAML; only
    # ${VAR} references. (.env itself is gitignored and excluded here.)
    import re
    files = [ROOT / "compose.yaml", ROOT / "compose.monitoring.yaml",
             ROOT / "compose.candidate.yaml",
             ROOT / ".github" / "workflows" / "ci.yml"]
    for f in files:
        for i, line in enumerate(f.read_text().splitlines(), 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            pat = r'(?i)(password|passwd|secret|token)\s*:\s*["\']?[A-Za-z0-9_\-]{8,}["\']?$'
            hit = re.search(pat, s) and "${" not in s
            assert not hit, f"{f.name}:{i} looks like a literal secret"


def test_gitleaks_gate_scans_explicit_paths():
    # M9/D32: a .gitleaks.toml allowlist SILENTLY DISABLES all default rules
    # in gitleaks v8 (proven live against a planted secret), so the gate must
    # never rely on one — and must never blanket-scan `.` (venv noise).
    assert not (ROOT / ".gitleaks.toml").exists(), \
        ".gitleaks.toml neuters default rules; explicit paths instead"
    ci = (ROOT / "scripts" / "ci.sh").read_text()
    assert "--no-git" in ci
    for d in ("services", "scripts", "terraform", "compose.yaml", ".env.example"):
        assert d in ci, f"ci.sh gitleaks gate does not scan {d}"
    assert "ci-plant" in ci, "block demo plants no secret"


def test_no_hardcoded_credentials_in_source():
    # M9: connection strings come from env, never literals. Gitleaks is the
    # scanner; this is the build-breaking backstop over services/+scripts/.
    import re
    hits = []
    for base in ("services", "scripts"):
        for f in (ROOT / base).rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            for i, line in enumerate(f.read_text().splitlines(), 1):
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if re.search(r'(?i)(password|passwd|secret|auth_token)\s*=\s*["\'][^"\']+["\']', s):
                    hits.append(f"{f.name}:{i}")
                if re.search(r'(postgres|redis|rediss)://[^"\s]*:[^"\s]+@', s):
                    hits.append(f"{f.name}:{i} (embedded userinfo)")
    assert not hits, f"hardcoded credentials: {hits}"


def test_ci_stages_thirteen():
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    jobs = ci["jobs"]
    for j in ("lint", "test", "integration", "secrets", "depsec", "iac",
              "build", "imagescan", "release", "audit"):
        assert j in jobs, f"CI job {j} missing"
    assert ci["permissions"]["contents"] == "read"
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "ruff check services tests scripts loadgen" in text  # stage 4
    assert "bash scripts/m1-verify.sh" in text  # stage 3 live
    assert "bash scripts/net-audit.sh" in text
    assert "gitleaks/gitleaks-action" in text  # stage 5
    for f in ("services/api/requirements.txt", "loadgen/requirements.txt"):
        assert f in text, f"depsec misses {f}"  # stage 6, all six files
    assert "fmt -check" in text and "checkov -d terraform/" in text  # stage 7
    assert "API_TAG=ci docker compose build" in text  # stage 8
    assert "healthcare-api:ci" in text  # stage 9
    assert "bash scripts/deploy.sh" in text  # stage 10
    assert "/api/v1/db/stats" in text  # stage 11 dep check
    assert "bash scripts/rollback.sh" in text  # stage 13
    assert "GITHUB_STEP_SUMMARY" in text and "upload-artifact" in text  # audit
    assert 'github.ref == ' in text, "release must be main-gated"


def test_ci_sh_mirrors_pipeline():
    src = (ROOT / "scripts" / "ci.sh").read_text()
    for stage in ("ruff", "m1-verify.sh", "net-audit.sh", "ci-report.jsonl",
                  "--demo-block", "PIPELINE BLOCKED", "terraform-validate-dev"):
        assert stage in src, f"ci.sh missing {stage}"


def test_compose_version_proves_release():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    env = compose["services"]["api"]["environment"]
    assert env["API_VERSION"] == "${API_VERSION:-m3}"


def test_break_ready_hook(monkeypatch):
    # M11 v3 drill: BREAK_READY=1 fails readiness WITHOUT touching deps.
    c = TestClient(api.app)
    monkeypatch.setenv("BREAK_READY", "1")
    r = c.get("/ready")
    assert r.status_code == 503
    assert r.json()["broken"] == "BREAK_READY"
    monkeypatch.delenv("BREAK_READY")
    r = c.get("/ready")
    assert "broken" not in r.json()  # hook off: normal dep-based answer


def test_version_in_logs_and_health():
    import inspect
    assert '"version"' in inspect.getsource(api.evt), "evt() must stamp version"
    assert TestClient(api.app).get("/health").json()["version"] == api.VERSION


def test_deploy_v3_drill_and_smoke():
    src = (ROOT / "scripts" / "deploy.sh").read_text()
    assert "--broken" in src and "BREAK_READY" in src
    for step in ("smoke", "/api/v1/db/stats", "/api/v1/jobs",
                 "bash scripts/rollback.sh", "serving version"):
        assert step in src, f"deploy.sh missing {step}"
    # Auto-rollback (not manual) on post-switch failure:
    assert src.count("bash scripts/rollback.sh") >= 2


def test_candidate_break_passthrough():
    cand = yaml.safe_load((ROOT / "compose.candidate.yaml").read_text())
    env = cand["services"]["api-candidate"]["environment"]
    assert env["BREAK_READY"] == "${BREAK_READY:-0}"


def test_backup_restore_verify():
    bkp = (ROOT / "scripts" / "backup.sh").read_text()
    for step in ("pg_dump", ".counts", "COPY public.",
                 "BACKUP FAIL", "BACKUP OK"):
        assert step in bkp, f"backup.sh missing {step}"
    rst = (ROOT / "scripts" / "restore.sh").read_text()
    for step in ("RESTORE REFUSED", "yes/no", "ON_ERROR_STOP=1",
                 "counts match", "RESTORE OK"):
        assert step in rst, f"restore.sh missing {step}"


def test_deploy_records_actor():
    for f in ("scripts/deploy.sh", "scripts/rollback.sh"):
        src = (ROOT / f).read_text()
        assert "ACTOR=" in src and "DEPLOY_ACTOR" in src, f"{f} missing actor"
        assert '"actor"' in src, f"{f} does not record actor"


def test_incident_reports_nine_fields():
    text = (ROOT / "INCIDENTS.md").read_text()
    for inc in ("INCIDENT-1", "INCIDENT-2"):
        assert inc in text, f"{inc} missing"
    for n, field in ((1, "Failure"), (2, "Impact"), (3, "Detection"),
                     (4, "Investigation"), (5, "Root cause"), (6, "Evidence"),
                     (7, "Recovery"), (8, "Verification"), (9, "Prevention")):
        assert text.count(f"{n}. {field}") >= 2, f"field {n}. {field} not in both reports"
    assert text.count("T+") >= 10, "timelines missing"
    assert "PENDING-ENGINE" in text, "live evidence must be marked, not assumed"


def test_spof_covers_seven_systems():
    rec = (ROOT / "RECOVERY.md").read_text()
    for sys in ("API", "Worker", "Queue", "Database", "EHR", "Deploy",
                "Monitoring"):
        assert sys in rec, f"SPOF analysis missing {sys}"
    for col in ("RTO", "RPO", "recreation", "recover"):
        assert col.lower() in rec.lower(), f"RECOVERY.md missing {col}"


def test_auditability_answers_eight():
    aud = (ROOT / "AUDITABILITY.md").read_text()
    for q in ("Who initiated", "What version", "infrastructure changed",
              "security checks", "succeed", "fail", "incident occur",
              "recovery action"):
        assert q.lower() in aud.lower(), f"auditability missing '{q}'"


def test_cost_covers_all_technologies():
    cost = (ROOT / "COST.md").read_text()
    for tech in ("Docker", "Nginx", "Redis", "PostgreSQL", "Terraform",
                 "GitHub Actions", "Prometheus", "Grafana", "Trivy",
                 "Gitleaks", "Checkov", "Python/FastAPI"):
        assert tech in cost, f"COST.md missing {tech}"
    for col in ("Why chosen", "Alternatives", "Trade-off"):
        assert col in cost, f"COST.md missing column {col}"


def test_cost_tensions_and_model():
    cost = (ROOT / "COST.md").read_text()
    for dimension in ("reliability", "performance", "security",
                      "simplicity", "cost"):
        assert dimension in cost.lower(), f"tension missing {dimension}"
    for bucket in ("dynamically", "minimal", "watchlist",
                   "overprovisioning", "egress"):
        assert bucket in cost.lower(), f"COST.md missing {bucket}"
    assert "$0" in cost, "zero-spend posture lost"
    assert "local" in cost.lower() and "cloud" in cost.lower()


def test_primary_diagram_exists():
    mmd = (ROOT / "docs" / "architecture.mmd").read_text()
    assert "flowchart" in mmd
    for node in ("EDGE", "INTERNAL", "NGINX", "API", "Redis", "PostgreSQL",
                 "Prometheus", "Grafana"):
        assert node.lower() in mmd.lower(), f"diagram missing {node}"


def test_ai_disclosure_present():
    text = (ROOT / "DECISIONS.md").read_text()
    assert "## D15" in text and "31" in text, "AI-assistance disclosure missing"
    assert "FINAL_REQUIREMENTS_AUDIT" in text


def test_demo_runbook_timed_narrative():
    demo = (ROOT / "DEMO_RUNBOOK.md").read_text()
    assert demo.count("### Step ") == 26, "demo must have 26 timed steps"
    assert "STEPS 27" in demo, "flex steps 27-31 missing"
    assert "APPENDIX" in demo
    assert "21 min" in demo, "time budget missing"
    assert demo.count("Fallback:") >= 26, "every step needs a fallback"
    assert demo.count("Expect:") >= 26, "every step needs expected output"
    for cue in ("deploy.sh v2", "--broken", "rollback.sh", "ci.sh --demo-block",
                "backup.sh", "restore.sh", "alerts.ps1", "fail-worker.ps1",
                "architecture.mmd"):
        assert cue in demo, f"demo missing {cue}"


def test_pdf_endpoint_aliases():
    c = TestClient(api.app)
    assert c.get("/version").json()["version"] == api.VERSION
    assert c.get("/version").json()["service"] == "api"


def test_ehr_admin_aliases():
    c = TestClient(ehr.app)
    try:
        assert c.post("/admin/mode", json={"mode": "slow"}).json() == {"mode": "slow"}
        assert c.get("/health").json()["mode"] == "slow"
        body = c.post("/ehr/sync", json={"job_id": 3}).json()
        assert body["outcome"] == "applied" and body["correlation_id"] == "none"
    finally:
        ehr.MODE = "normal"


def test_worker_processing_seconds_metric():
    import inspect
    src = inspect.getsource(worker.Handler.do_GET)
    assert "worker_processing_seconds" in src
    assert "hincrbyfloat" in inspect.getsource(worker)


def test_docs_required_files():
    for f in ("ARCHITECTURE.md", "CI_CD.md", "RELIABILITY.md", "SCALABILITY.md",
              "RESILIENCE_ANALYSIS.md", "ACCESS_AND_AUDIT.md", "CLOUD_MIGRATION.md"):
        assert (ROOT / "docs" / f).exists(), f"docs/{f} missing"
    for f in ("AI_ASSISTANCE.md", "SECURITY_REPORT.md", "INCIDENT_REPORT.md"):
        assert (ROOT / f).exists(), f"{f} missing"


def test_traceability_exact_columns_34_sections():
    lines = (ROOT / "REQUIREMENTS_TRACEABILITY.md").read_text().splitlines()
    header = next(ln for ln in lines if ln.startswith("| PDF Section"))
    for col in ("PDF Section", "Requirement", "Implementation", "Files",
                "Test/Scenario", "Evidence", "Status"):
        assert col in header, f"column {col} missing"
    rows = [ln for ln in lines if ln.startswith("| ")
            and not ln.startswith("| PDF")]
    assert len(rows) == 34, f"want 34 section rows, got {len(rows)}"
    assert not any("| FAIL |" in r for r in rows), "FAIL rows present"


def test_audit_answers_34_questions():
    text = (ROOT / "FINAL_REQUIREMENTS_AUDIT.md").read_text()
    for n in list(range(1, 11)) + list(range(19, 35)):
        assert f"{n}." in text, f"audit answer {n} missing"
    assert "11" in text and "15." in text, "audit range 11-15 missing"
    assert "16" in text and "18." in text, "audit range 16-18 missing"


def test_demo_phase_map():
    demo = (ROOT / "DEMO_RUNBOOK.md").read_text()
    assert "PHASE" in demo and "Step" in demo


# --- worker policy (pure functions) ---

def test_classify_matrix():
    w = worker.classify
    assert w(200, {"outcome": "applied"}) == "ok"
    assert w(200, {"outcome": "unknown"}) == "unknown"
    assert w(200, {}) == "ok"
    for code in (400, 401, 403, 404, 422):
        assert w(code, {}) == "permanent", code
    for code in (408, 429, 500, 502, 503, 504, 418, None):
        assert w(code, {}) == "temporary", code


def test_retry_delay_backoff():
    assert worker.retry_delay(1) == 2.0
    assert worker.retry_delay(2) == 4.0
    assert worker.retry_delay(3) == 8.0
    assert worker.retry_delay(99) == worker.BACKOFF_CAP
    assert worker.MAX_ATTEMPTS == 3 and worker.TIMEOUT == 5.0


def test_worker_constants():
    assert worker.QUEUE == "jobs:queue"
    assert worker.PROCESSING == "jobs:processing"
    assert worker.DELAYED == "jobs:delayed"


def test_queue_stats_math():
    s = api.queue_stats(10, 2, 1000.0, now=1060.0)
    assert s == {"queue_depth": 10, "delayed": 2, "oldest_age_s": 60.0}
    assert api.queue_stats(0, 0, None)["oldest_age_s"] == 0.0
    # Clock skew safe: future timestamp never yields negative age.
    assert api.queue_stats(1, 0, 2000.0, now=1000.0)["oldest_age_s"] == 0.0


def test_worker_env_validation():
    try:
        worker._num("ANYTHING", "abc", float)
        raise AssertionError("bad config did not exit")
    except SystemExit as e:
        assert "invalid" in str(e)
    assert worker._num("ANYTHING", "2.5", float) == 2.5


def test_worker_healthcheck_in_compose():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    hc = " ".join(compose["services"]["worker"]["healthcheck"]["test"])
    assert "8003/health" in hc


def test_failure_scripts_exist():
    expected = ["fail-service.ps1", "recover-service.ps1",
                "fail-worker.ps1", "recover-worker.ps1",
                "fail-api.ps1", "recover-api.ps1",
                "fail-db.ps1", "recover-db.ps1",
                "ehr-failure.ps1", "ehr-recover.ps1",
                "load-test.ps1", "fail-config.ps1", "recover-config.ps1",
                "measure-api.ps1", "measure-workers.ps1", "measure-startup.ps1",
                "scale-api.ps1", "scale-worker.ps1", "alerts.ps1"]
    missing = [f for f in expected if not (ROOT / "scripts" / f).exists()]
    assert not missing, f"missing failure scripts: {missing}"
