#!/usr/bin/env bash
# Restore a `nodestro-server backup` (pg_dump, custom format) into the compose stack's database.
#
#   scripts/restore.sh backups/nodestro-20261031T120000Z.dump
#
# Stops the API and the worker, replaces the database's contents in one transaction (nothing changes if any step
# fails), applies migrations if the dump is older than the image, and starts the API and the worker again.
# Production: docs/RUNBOOK.md (the same steps against your own PostgreSQL).
set -euo pipefail
dump="${1:?usage: restore.sh DUMP}"
test -s "$dump" || { echo "no dump at $dump" >&2; exit 1; }
export COMPOSE_FILE="${COMPOSE_FILE:-$(cd "$(dirname "$0")/.." && pwd)/compose/compose.yaml}"
docker compose stop api worker
# pg_restore of the server image: the same version as the pg_dump that wrote the backup (a dump of a newer pg_dump
# cannot be read by an older pg_restore). The password goes to it in its environment, never on the command line.
dir="$(cd "$(dirname "$dump")" && pwd)"
docker compose run --rm --no-deps -T -v "$dir/$(basename "$dump"):/restore/backup.dump:ro" --entrypoint python api -I -c '
import os
from psycopg.conninfo import conninfo_to_dict, make_conninfo
with open("/run/secrets/database_url", encoding="utf-8") as file:
    parts = conninfo_to_dict(file.read().strip())
environment = dict(os.environ)
password = parts.pop("password", None)
if password is not None:
    environment["PGPASSWORD"] = str(password)
os.execvpe("pg_restore", ["pg_restore", "--clean", "--if-exists", "--no-owner", "--single-transaction",
    "--exit-on-error", "--dbname=" + make_conninfo("", **parts), "/restore/backup.dump"], environment)
'
docker compose run --rm --no-deps -T migrate
docker compose up -d --no-deps api worker
echo "restored $dump"
