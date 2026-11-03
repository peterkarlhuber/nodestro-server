#!/usr/bin/env bash
# Restore a `nodestro-server backup` (pg_dump, custom format) into the compose stack's database.
#
#   scripts/restore.sh backups/nodestro-20261031T120000Z.dump
#
# Stops the API and the worker, replaces the database's contents in one transaction (nothing changes if any step
# fails) as the owner role nodestro_owner (database_migration_url; the restored objects belong to it), applies
# migrations if the dump is older than the image (which also grants nodestro_app its privileges again), and starts the
# API and the worker again.
# Production: docs/RUNBOOK.md (the same steps against your own PostgreSQL).
set -euo pipefail
dump="${1:?usage: restore.sh DUMP}"
test -s "$dump" || { echo "no dump at $dump" >&2; exit 1; }
export COMPOSE_FILE="${COMPOSE_FILE:-$(cd "$(dirname "$0")/.." && pwd)/compose/compose.yaml}"
docker compose stop api worker
# The restore runs in the server image (scripts/restore_dump.py: its pg_restore and psql are the same version as the
# pg_dump that wrote the backup; extensions are left out; the newer release's tables that are not in the dump are
# dropped; one transaction). The password goes to the tools in their environment, never on the command line.
dir="$(cd "$(dirname "$dump")" && pwd)"
here="$(cd "$(dirname "$0")" && pwd)"
docker compose run --rm --no-deps -T -v "$dir/$(basename "$dump"):/restore/backup.dump:ro" \
  -v "$here/restore_dump.py:/restore/restore_dump.py:ro" --entrypoint python migrate -I /restore/restore_dump.py \
  /restore/backup.dump
docker compose run --rm --no-deps -T migrate
docker compose up -d --no-deps api worker
echo "restored $dump"
