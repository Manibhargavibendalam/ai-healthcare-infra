#!/usr/bin/env bash
# PDF §20 alias: `backup-db` forwards to the canonical `backup.sh`
# (single implementation, two entry names — no duplicated logic).
# Run from repo root:  bash scripts/backup-db.sh
set -uo pipefail
exec bash "$(dirname "$0")/backup.sh"
