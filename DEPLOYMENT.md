# DEPLOYMENT & ROLLBACK (M8/M11)

Strategy: verify-before-replace (blue/green without an orchestrator).
`scripts/deploy.sh <version> [--broken]` / `scripts/rollback.sh [version]`.
CI calls deploy.sh with the commit sha; a non-zero exit blocks the pipeline.

## Versioning

`api` images are tagged `healthcare-api:<version>` (`API_TAG` in compose).
The version surfaces in THREE places: `GET /health` response (`version`
field, via `API_VERSION`), every log line (`evt()` stamps `version`), and
`api_build_info{version}` for Prometheus/Grafana (panel 10). Releases append
to `deployments.jsonl` (gitignored runtime history):
`{"version":"v12","ts":"...","prev":"v11"}`.

## The v1 → v2 → v3 demonstration (exact commands)

```powershell
bash scripts/deploy.sh v1       # healthy: 10 steps, v1 serves (prove: curl :8080/health → "version":"v1")
bash scripts/deploy.sh v2       # healthy: candidate gated, switched, v2 serves, history prev=v1
bash scripts/deploy.sh v3 --broken  # FAILURE DRILL: candidate gets BREAK_READY=1,
                                    # /ready 503s, gate times out → candidate destroyed,
                                    # api untouched → v2 still serves → failed posted → exit 1
curl.exe -s http://127.0.0.1:8080/health   # still "version":"v2" — the proof
bash scripts/rollback.sh        # rolls to prev (v1), verifies via ingress, records entry
```

## Sequence (healthy release, 10 steps)

```
deploy.sh v2
  1. structural gate: docker compose config --quiet (F7-class errors die here)
  2. build healthcare-api:v2
  3. up api-candidate (internal only, restart:no, same tag)
  4. poll candidate /ready via exec (120s) — health checks + dependency verification
  5. smoke dependencies (candidate must reach db/redis: /ready IS the dep check)
  6. recreate api from the VERIFIED tag (traffic shifts via nginx
     resolver TTL ≤5s; old containers removed only now)
  7. poll :8080/ready via ingress (120s)
  8. version-under-traffic: /health version == v2 THROUGH the ingress
  9. smoke enqueue: POST job → accepted (api→db→redis path, worker-independent)
  10. rm candidate, record history, POST /deploys{ok} to alert-api
```

## Sequence (broken release, 7 steps)

`deploy.sh v3 --broken` sets `BREAK_READY=1` on the candidate ONLY (the
failure injector, same philosophy as `EHR_MODE` — no source patching):

```
  1. candidate starts with BREAK_READY=1
  2. candidate /ready → 503 {"not_ready","broken":"BREAK_READY"}
  3. gate times out → deployment STOPS
  4. candidate destroyed; api untouched, v2 keeps serving
  5. /deploys{failed} posted (DeployFailed alert fires)
  6. exit 1 (CI red, no further stages)
  7. evaluator proves v2 alive: /health version + probe job
```

Nothing to roll back — the unsafe release never received traffic. If a failure
ever slips PAST the switch (ingress not ready / smoke red), deploy.sh
AUTO-runs `rollback.sh` itself instead of telling the operator to.

## Rollback

`rollback.sh` re-pins `api` to the last `prev` (or an explicit version),
verifies via ingress, records a `(rollback)` entry. Refuses with exit 1
when history is empty — it never guesses a version. A rollback is itself a
deploy: same gate, same verification, same alert post.

## Failure modes

| Failure | Behavior |
|---|---|
| Bad compose edit | step 1 aborts before any container moves |
| Build breaks | exit 1, old version serving |
| Candidate crash-loops | `restart:no` keeps it visibly dead; gate times out; api untouched |
| Candidate /ready 503s (`--broken` drill or real bug) | gate times out; the standard blocked-release path |
| api recreate fails mid-switch | candidate KEPT for inspection; auto-rollback attempted |
| Post-switch ingress/smoke red | AUTO-rollback runs inline; failed posted; exit 1 |

## Deploy vs F7 config drill

F7 (`fail-config.ps1`) proves a bad VALUE fails safe at runtime. Deploy.sh
proves a bad RELEASE never ships: structural gate + readiness gate +
versioned history + one-command rollback. Same philosophy, different layer.
