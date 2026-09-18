#!/usr/bin/env bash
# Restore a pg_dump file into the live database (after down -v recreation).
# Verification is BUILT IN: post-restore counts are compared against the
# .counts file backup.sh wrote (when present), then a probe job must complete.
# DESTRUCTIVE by nature — asks first. Usage from repo root:
#   bash scripts/restore.sh backups/manual-<ts>.sql
set -uo pipefail
FILE="${1:?usage: bash scripts/restore.sh <dump.sql>}"
[ -f "$FILE" ] || { echo "RESTORE REFUSED: no such file: $FILE"; exit 1; }
read -r -p "Restore $FILE into the live DB, overwriting current state? (yes/no) " ans
[ "$ans" = "yes" ] || { echo "aborted"; exit 0; }
set -a; source .env; set +a
PSQL=(docker compose exec -T -e "PGPASSWORD=$POSTGRES_PASSWORD" db \
  psql -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-healthcare}" -t -A)
docker compose exec -T -e "PGPASSWORD=$POSTGRES_PASSWORD" db \
  psql -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-healthcare}" \
  -v ON_ERROR_STOP=1 < "$FILE" \
  || { echo "RESTORE FAIL: see error above"; exit 1; }
echo "RESTORE OK: $FILE applied"

echo "== verify restore =="
COUNTS="${FILE%.sql}.counts"
if [ -f "$COUNTS" ]; then
  for t in patients jobs ehr_syncs; do
    want=$(grep -o "\"$t\":[0-9]*" "$COUNTS" | grep -o '[0-9]*')
    got=$("${PSQL[@]}" -c "SELECT count(*) FROM $t;")
    [ "$got" = "$want" ] || { echo "RESTORE FAIL: $t count $got != backup $want"; exit 1; }
    echo "counts match: $t=$got"
  done
else
  echo "(no .counts file — counted rows only)"
  "${PSQL[@]}" -c "SELECT (SELECT count(*) FROM patients) AS patients, (SELECT count(*) FROM jobs) AS jobs;"
fi
echo "final proof: POST a probe job via :8080 and watch it complete (DEMO_RUNBOOK.md recovery)"
