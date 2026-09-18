#!/usr/bin/env bash
# PDF §20 alias: `restore-db` forwards to the canonical `restore.sh`.
# Run from repo root:  bash scripts/restore-db.sh backups/manual-<ts>.sql
set -uo pipefail
exec bash "$(dirname "$0")/restore.sh" "$@"
