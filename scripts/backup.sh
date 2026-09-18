#!/usr/bin/env bash
# pg_dump the live database to backups/ (state recovery source of truth).
# Verification is BUILT IN, not a separate manual step:
#   1. pre-backup row counts (patients/jobs/ehr_syncs) saved to <.counts>
#   2. dump header + per-table COPY markers + byte size asserted
# Recreation (compose down -v/up) is SEPARATE from recovery (this file +
# restore.sh, which compares against the .counts file) — see RECOVERY.md.
# Run from repo root in Git Bash.
set -uo pipefail
set -a; source .env; set +a
PSQL=(docker compose exec -T -e "PGPASSWORD=$POSTGRES_PASSWORD" db \
  psql -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-healthcare}" -t -A)
mkdir -p backups
TS=$(date -u +%FT%H%MZ)
OUT="backups/manual-$TS.sql"

echo "== pre-backup counts =="
PATIENTS=$("${PSQL[@]}" -c "SELECT count(*) FROM patients;") \
  || { echo "BACKUP FAIL: is the stack up? (docker compose ps)"; exit 1; }
JOBS=$("${PSQL[@]}" -c "SELECT count(*) FROM jobs;")
SYNCS=$("${PSQL[@]}" -c "SELECT count(*) FROM ehr_syncs;")
echo "patients=$PATIENTS jobs=$JOBS ehr_syncs=$SYNCS"
printf '{"ts":"%s","patients":%s,"jobs":%s,"ehr_syncs":%s}\n' \
  "$TS" "$PATIENTS" "$JOBS" "$SYNCS" > "${OUT%.sql}.counts"

echo "== dump =="
docker compose exec -T -e "PGPASSWORD=$POSTGRES_PASSWORD" db \
  pg_dump -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-healthcare}" > "$OUT" \
  || { echo "BACKUP FAIL: pg_dump errored"; exit 1; }

echo "== verify dump =="
grep -q 'PostgreSQL database dump' "$OUT" || { echo "BACKUP FAIL: bad header"; exit 1; }
for t in patients jobs ehr_syncs appointments doctors hospitals; do
  grep -q "COPY public.$t " "$OUT" || { echo "BACKUP FAIL: table $t missing"; exit 1; }
done
[ "$(wc -c < "$OUT")" -gt 1024 ] || { echo "BACKUP FAIL: dump suspiciously small"; exit 1; }
echo "BACKUP OK: $OUT ($(wc -c < "$OUT") bytes, counts in ${OUT%.sql}.counts)"
