# NETWORKING

Enforced by `compose.yaml` (`edge` + `internal` bridge networks), not by
documentation. Audit live with `bash scripts/net-audit.sh`.

```
Internet / operator (host-local 127.0.0.1 only)
  │ :8080
  ▼
┌──────── edge ────────┐
│ NGINX (unprivileged) │  can ONLY see api (sole edge peer)
└────────┬─────────────┘
         ▼ :8000
┌──────── internal ───────────────────────────────┐
│ API ◄─► AI :8001 · EHR :8002 · Redis · Postgres │
│ Worker ──► AI/EHR/Redis/Postgres (no ports)     │
└─────────────────────────────────────────────────┘
```

## Membership & ports

| Service | Networks | Host ports | Why |
|---|---|---|---|
| nginx | edge | 127.0.0.1:8080 | the single public door; stateless, health-gated |
| api | edge + internal | none | DMZ bridge: only service allowed on both; never exposes internals in responses |
| ai / ehr-mock | internal | none | called only by api/worker; operator access via `exec` + `/scripts/svc.py` |
| worker | internal | none | no inbound need at all (polls Redis); metrics :8003 container-local |
| redis / postgres | internal | none | state + secrets; reachable only from api/worker |

## Why API is public (and only via nginx)

It is stateless, versioned, health-gated (`/ready` checks deps), and never
returns credentials or tracebacks. nginx adds one choke point for future
TLS/rate-limit/auth and (M4) traffic shifting. Direct `:8000` from the host
is refused — the e2e script asserts this.

## Why DB / Redis / worker / AI are private

- **Postgres**: holds all state incl. credentials-adjacent rows; compromise
  blast radius is total. Only api + worker need it (SG/task equivalent).
- **Redis**: unauthenticated-protocol risk + queue integrity; password required
  even inside; only api (push) + worker (pop) speak to it.
- **Worker**: polls outbound; zero inbound need → zero attack surface; liveness
  via heartbeat + container-local metrics, never a public socket.
- **AI**: internal capability with failure-injection modes; no caller outside
  api/worker exists.

## How EHR communication is controlled

Worker is the ONLY client (`EHR_URL=http://ehr:8002`, internal DNS). The EHR
initiates nothing inbound. Failure modes are server-side switches; true
unreachability is `docker compose stop ehr-mock` (connection-refused path).
Per-call timeout (5s) + bounded backoff retries + fail-fast auth + no-retry
unknown-outcome complete the control story (see DECISIONS.md D5/D16/D17).

## Proof commands (all in `scripts/net-audit.sh`)

- `docker compose port <svc> …` empty for all but nginx; `docker ps` shows one mapping.
- Negative test: temp container on `edge` reaches `api:8000` ✅ but `db:5432`
  and `redis:6379` time out ❌ (segmentation, not docs).
- Host: `Test-NetConnection 127.0.0.1 -Port 5432` fails; `:8080` succeeds.
- `docker stats` shows enforced `cpus`/`mem_limit` per service.
