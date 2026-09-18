#!/usr/bin/env bash
# Incremental migrations against a LIVE database (deploy-step story:
# schema changes ship separately from code). Fresh volumes are seeded
# automatically via initdb.d; this script covers already-running DBs.
# Needs: PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE in the environment.
# Usage (Git Bash):  PGPASSWORD=... bash scripts/migrate.sh
set -uo pipefail
: "${PGHOST:=127.0.0.1}" "${PGPORT:=5432}" "${PGUSER:=app}" "${PGDATABASE:=healthcare}"
PSQL=(docker compose exec -T -e "PGPASSWORD=$PGPASSWORD" db psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -t -A)
have() { "${PSQL[@]}" -c "SELECT 1 FROM schema_migrations WHERE version='$1';" | grep -q 1; }
for f in db/migrations/*.sql; do
  v=$(basename "$f" .sql)
  if have "$v"; then echo "SKIP $v (applied)"; continue; fi
  echo "APPLY $v"
  docker compose exec -T -e "PGPASSWORD=$PGPASSWORD" db psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -f "/docker-entrypoint-initdb.d/$(basename "$f")"
  "${PSQL[@]}" -c "INSERT INTO schema_migrations(version) VALUES ('$v');"
done
echo "migrations up to date"
