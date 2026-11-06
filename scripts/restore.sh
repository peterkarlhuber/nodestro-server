#!/usr/bin/env bash
# Restore a backup into the compose stack's database, and with a backup manifest also its data volume.
#
#   scripts/restore.sh backups/nodestro-backup-20261031T120000Z.json   # scripts/backup.sh: database and data volume
#   scripts/restore.sh backups/nodestro-20261031T120000Z.dump          # a `nodestro-server backup` dump: database only
#
# Stops the API and the worker, replaces the database's contents in one transaction (nothing changes if any step
# fails) as the owner role nodestro_owner (database_migration_url; the restored objects belong to it), applies
# migrations if the dump is older than the image (which also grants nodestro_app its privileges again), and starts the
# API and the worker again.
# With a manifest (scripts/backup.sh) the SHA-256 of every file is checked first (nothing is changed when one does not
# match), and the data volume is replaced by the archive of the same backup before the migrations run (its `backups`
# folder is kept). When the backup has an archive of Axentra's storage, `nodestro-server files verify` must then
# report every stored file present.
# Production: docs/RUNBOOK.md (the same steps against your own PostgreSQL).
set -euo pipefail
given="${1:?usage: restore.sh MANIFEST.json|DUMP}"
test -s "$given" || { echo "no backup at $given" >&2; exit 1; }
export COMPOSE_FILE="${COMPOSE_FILE:-$(cd "$(dirname "$0")/.." && pwd)/compose/compose.yaml}"
dir="$(cd "$(dirname "$given")" && pwd)"
here="$(cd "$(dirname "$0")" && pwd)"
data="" storage=""
case "$given" in
  *.json)
    # The manifest's files, after their checksums matched: "<dump> <data archive> [<storage archive>]".
    read -r dump data storage < <(python3 -I - "$given" <<'PY'
import hashlib, json, sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
manifest = json.loads(manifest_path.read_text())
if manifest.get("format") != 1:
    sys.exit(f"{manifest_path}: not a backup manifest of scripts/backup.sh (format 1)")
names = []
for key in ("database", "data", "storage"):
    item = manifest.get(key)
    if item is None and key == "storage":
        continue
    path = manifest_path.parent / Path(item["name"]).name
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != item["sha256"]:
        sys.exit(f"{path}: SHA-256 does not match the manifest; nothing was restored")
    names.append(path.name)
print(" ".join(names))
PY
)
    [ -n "${data:-}" ] || { echo "the manifest's checks failed; nothing was restored" >&2; exit 1; }
    ;;
  *) dump="$(basename "$given")" ;;
esac
docker compose stop api worker
# The restore runs in the server image (scripts/restore_dump.py: its pg_restore and psql are the same version as the
# pg_dump that wrote the backup; extensions are left out; the newer release's tables that are not in the dump are
# dropped; one transaction). The password goes to the tools in their environment, never on the command line.
docker compose run --rm --no-deps -T -v "$dir/$dump:/restore/backup.dump:ro" \
  -v "$here/restore_dump.py:/restore/restore_dump.py:ro" --entrypoint python migrate -I /restore/restore_dump.py \
  /restore/backup.dump
if [ -n "$data" ]; then
  # The data volume as it was at the backup: everything but the `backups` folder is replaced.
  docker compose run --rm --no-deps -T -v "$dir/$data:/restore/data.tar.gz:ro" --entrypoint sh migrate -ec \
    'find /var/lib/nodestro -mindepth 1 -maxdepth 1 ! -name backups -exec rm -rf {} +
     tar -C /var/lib/nodestro -xzf /restore/data.tar.gz'
  echo "restored the data volume from $data"
fi
docker compose run --rm --no-deps -T migrate
if [ -n "$storage" ]; then
  # Axentra's local storage (NODESTRO_FILES_BACKEND=axentra): in the development stack its folder is in the data volume,
  # which the data archive restored; elsewhere restore $storage into storage.local_path first. Every file the restored
  # database names must be there.
  docker compose run --rm --no-deps -T migrate files verify
fi
docker compose up -d --no-deps api worker
echo "restored $given"
