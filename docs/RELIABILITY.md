# RELIABILITY

How this system stays up, degrades gracefully, and recovers — with the local
limits stated openly (no cloud-HA pretense).

## Mechanisms

Healthchecks on all services + `depends_on: service_healthy` startup order;
`restart:unless-stopped` everywhere; failure isolation (one bad job never
kills the worker loop; DB outage parks jobs, api 503s without crashing);
bounded retries with exponential backoff (temp), fail-fast auth, no-retry
unknown outcomes; timeouts on every downstream call (worker 5s, AI 3s);
graceful degradation (appointments book with `risk=null` when AI is down);
independent api/worker scaling; blue/green deploys.

## Failure modes → drills

API/worker/container/EHR/backlog/DB/deploy/config → F1–F7 scripts
(`../scripts/fail-*.ps1` + recover pairs) and full lifecycles in
`../INCIDENTS.md` (INCIDENT-1 backlog, INCIDENT-2 EHR timeout, 9 fields each).

## Local limits (honest)

Single host, single replicas by default, single Redis/Postgres instances,
monitoring shares the host (fate-sharing), no multi-AZ. What survives:
process/container death (restart), dependency outage (degrade + retry),
bad release (blocked). What doesn't: host loss, AZ loss — accepted for a
local simulation, mitigated in cloud by the TF mirror (Multi-AZ options,
snapshots, HPA). Full SPOF table: `RESILIENCE_ANALYSIS.md`.
