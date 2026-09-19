#!/usr/bin/env bash
# Local CI mirror: same gates as .github/workflows/ci.yml, runnable without
# pushing (Git Bash). Stages: lint -> test -> security -> iac -> build ->
# integration (if stack up) -> report (ci-report.jsonl audit line).
# Every security/iac gate posts {name, ok} to alert-api /gates (best effort:
# needs the monitoring overlay up), feeding the SecurityGateFailing alert.
# Exit code = number of FAILED gates (0 = all runnable gates green).
# Stages that need the Docker daemon print SKIP when it is unreachable.
# Block demo:  bash scripts/ci.sh --demo-block   (plants a fake secret,
# watches gitleaks fail, cleans up, exits 1 — the pipeline blocking).
# Run from repo root.
set -uo pipefail
# Git Bash on Windows mangles /container/paths for docker.exe; all paths
# in this script are container-internal, so disable conversion entirely.
export MSYS2_ARG_CONV_EXCL='*'
PASS=0; FAIL=0; SKIP=0
GATES=()  # "name:ok|fail" for the alert-api post + summary

have_docker() { docker version --format '{{.Server.Version}}' >/dev/null 2>&1; }
have_tool() { command -v "$1" >/dev/null 2>&1; }

run_gate() { # $1=name $2...=command (run, do NOT fail fast)
  local name="$1"; shift
  if "$@" >/tmp/ci-"$name".log 2>&1; then
    echo "GATE PASS: $name"; PASS=$((PASS+1)); GATES+=("$name:ok")
  else
    echo "GATE FAIL: $name (see /tmp/ci-$name.log)"
    tail -n 5 /tmp/ci-"$name".log
    FAIL=$((FAIL+1)); GATES+=("$name:fail")
  fi
}

skip_gate() { echo "GATE SKIP: $1 ($2)"; SKIP=$((SKIP+1)); }

post_gates() { # best effort: alert-api lives behind the monitoring overlay
  for g in "${GATES[@]:-}"; do
    local n="${g%%:*}" v="${g##*:}"
    [ "$v" = ok ] && ok=true || ok=false
    docker compose -f compose.yaml -f compose.monitoring.yaml exec -T alert-api \
      python /scripts/svc.py 8080 POST /gates \
      "{\"name\":\"$n\",\"ok\":$ok}" >/dev/null 2>&1 || true
  done
  [ "${#GATES[@]}" -gt 0 ] && echo "(gate results posted to alert-api where reachable)" || true
}

DEMO_BLOCK=0
[ "${1:-}" = "--demo-block" ] && DEMO_BLOCK=1

echo "== ci.sh: lint stage (stage 4) =="
if [ -x .venv/Scripts/ruff.exe ]; then
  run_gate ruff .venv/Scripts/ruff.exe check services tests scripts loadgen
elif have_tool ruff; then
  run_gate ruff ruff check services tests scripts loadgen
else
  skip_gate ruff "venv tool missing (pip install ruff)"
fi

echo "== ci.sh: test stage (stage 3) =="
if have_tool pytest || [ -x .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe
  [ -x "$PY" ] || PY=python
  run_gate pytest "$PY" -m pytest tests/ -q
else
  skip_gate pytest "no python/venv on PATH"
fi

echo "== ci.sh: security stage =="
if [ "$DEMO_BLOCK" = 1 ]; then
  PLANT="ci-plant-$RANDOM.tmp"
  # Proven-detected dummy, stored SPLIT so this script itself stays clean:
  # gitleaks allowlists the documented AWS EXAMPLE key and ignores weak
  # randomness, but flags this exact value (verified live) — while neither
  # half alone trips the rule (verified below by the clean-run gate).
  # Fake, untracked, removed on exit by the trap below.
  P1='9f8k2mQx7ZvB4nL6wT3yHj5sD'
  P2='F8g-PROD'
  printf 'db_password = "%s%s"\n' "$P1" "$P2" > "$PLANT"
  trap 'rm -f "$PLANT"' EXIT
  echo "(planted random dummy secret in $PLANT — untracked, removed on exit)"
fi
if have_tool gitleaks; then
  # Explicit path list, NOT `.`: .venv/ + .terraform/ are tool caches whose
  # vendored example keys would drown the gate in 350+ false positives, and
  # a .gitleaks.toml allowlist is FORBIDDEN (it silently disables all default
  # rules in gitleaks v8 — proven live, see D32). Untracked drill files like
  # ci-plant-*.tmp ARE scanned (--no-git covers the working tree).
  glance() {
    local fail=0
    for target in services scripts monitoring nginx loadgen tests terraform \
                  docker db .github compose.yaml compose.monitoring.yaml \
                  compose.candidate.yaml .env.example ci-plant-*.tmp \
                  *.md Dockerfile; do
      [ -e "$target" ] || continue
      gitleaks detect --source "$target" --no-git -v >>/tmp/ci-gitleaks.log 2>&1 \
        || fail=1
    done
    return $fail
  }
  run_gate gitleaks glance
else
  skip_gate gitleaks "not on PATH"
fi
if have_tool trivy; then
  run_gate trivy trivy fs --scanners vuln,misconfig --severity HIGH,CRITICAL \
    --skip-dirs .terraform,.venv,.git --no-progress .
else
  skip_gate trivy "not on PATH"
fi
if [ -x .venv/Scripts/pip-audit.exe ]; then
  run_gate pip-audit .venv/Scripts/pip-audit.exe \
    -r services/api/requirements.txt -r services/worker/requirements.txt \
    -r services/ai-service/requirements.txt -r services/ehr-mock/requirements.txt \
    -r services/alert-api/requirements.txt -r loadgen/requirements.txt
else
  skip_gate pip-audit "venv tool missing (pip install pip-audit)"
fi
# Checkov cannot run on hosts whose App Control blocks its rustworkx DLL
# (this machine — import fails even though the package installs); CI
# (ubuntu-latest) runs it — see .github/workflows/ci.yml. Trivy misconfig
# above is the local IaC-policy equivalent.
if have_tool checkov; then
  run_gate checkov checkov -d terraform/ --framework terraform --soft-fail-on LOW,MEDIUM --compact
elif [ -d .venv/Lib/site-packages/checkov ]; then
  skip_gate checkov "installed but App-Control-blocked on this host (runs in CI)"
else
  skip_gate checkov "not installed (runs in CI; trivy-misconfig covers IaC locally)"
fi

echo "== ci.sh: iac stage =="
if have_tool terraform; then
  run_gate terraform-fmt terraform -chdir=terraform fmt -check -recursive
  if [ -d terraform/environments/dev/.terraform ] && [ -d terraform/environments/prod/.terraform ]; then
    run_gate terraform-validate-dev terraform -chdir=terraform/environments/dev validate
    run_gate terraform-validate-prod terraform -chdir=terraform/environments/prod validate
  else
    skip_gate terraform-validate "run terraform init -backend=false in each env first"
  fi
else
  skip_gate terraform-fmt "not on PATH"
  skip_gate terraform-validate "not on PATH"
fi
if have_docker; then
  run_gate compose-config docker compose config --quiet
else
  skip_gate compose-config "docker daemon unreachable"
fi

echo "== ci.sh: build stage =="
if have_docker; then
  run_gate compose-build docker compose build
else
  skip_gate compose-build "docker daemon unreachable"
fi

echo "== ci.sh: integration stage (live e2e, needs the stack up) =="
if have_docker && docker compose ps --format '{{.Name}}' 2>/dev/null | grep -q api; then
  run_gate e2e bash scripts/m1-verify.sh
  run_gate net-audit bash scripts/net-audit.sh
else
  skip_gate e2e "stack not running (up first, or runs in CI)"
  skip_gate net-audit "stack not running (runs in CI)"
fi

echo "== ci.sh: report + audit record =="
post_gates
SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "uncommitted")
printf '{"ts":"%s","commit":"%s","pass":%d,"fail":%d,"skip":%d}\n' \
  "$(date -u +%FT%TZ)" "$SHA" "$PASS" "$FAIL" "$SKIP" >> ci-report.jsonl
echo "audit: appended to ci-report.jsonl"
echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
if [ "$FAIL" -gt 0 ]; then
  echo "PIPELINE BLOCKED: $FAIL gate(s) red — no deploy."
  exit 1
fi
echo "PIPELINE GREEN (runnable gates only; $SKIP skipped — see above)."
