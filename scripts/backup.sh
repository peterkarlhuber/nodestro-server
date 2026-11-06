#!/usr/bin/env bash
# A consistent backup of the compose stack: the database and the data volume (NODESTRO_DATA_DIR, the tenants' files)
# from one point in time, plus a manifest that pairs them.
#
#   scripts/backup.sh DIR
#
# 1. Stops the API and the worker, so nothing writes to the database or the data volume while the backup runs (the
#    studio is unavailable for that time, usually seconds to minutes).
# 2. `nodestro-server backup` as the owner role (the migrate service): pg_dump, and with NODESTRO_FILES_BACKEND=axentra
#    on the local backend also the archive of Axentra's storage.
# 3. A tar of the data volume, without its `backups` folder (pre-migration dumps of `migrate --backup-dir`).
# 4. `nodestro-backup-<time>.json`: the files of this backup with size and SHA-256, the image and the time.
# 5. Starts the API and the worker again (also when a step failed), if they were running before.
#
# scripts/restore.sh DIR/nodestro-backup-<time>.json restores all of it. Production: docs/RUNBOOK.md, "Backup and
# restore" (the same steps against your own PostgreSQL and volume).
set -euo pipefail
out="${1:?usage: backup.sh DIR}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
chmod 0777 "$out" # the image runs as user 10001
export COMPOSE_FILE="${COMPOSE_FILE:-$(cd "$(dirname "$0")/.." && pwd)/compose/compose.yaml}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
running="$(docker compose ps --status running --services api worker 2>/dev/null | tr '\n' ' ')"
restart() {
  status=$?
  if [ -n "${running// /}" ]; then
    # shellcheck disable=SC2086 # the service names, word-split on purpose
    docker compose start $running >/dev/null || status=1
  fi
  exit "$status"
}
trap restart EXIT
docker compose stop api worker >/dev/null

printed="$(docker compose run --rm --no-deps -T -v "$out:/backups" migrate backup /backups)"
dump="$(printf '%s\n' "$printed" | sed -n 's|^/backups/\(.*\.dump\)$|\1|p' | tail -n 1)"
storage="$(printf '%s\n' "$printed" | sed -n 's|^/backups/\(.*\.tar\.gz\)$|\1|p' | tail -n 1)"
[ -n "$dump" ] && [ -s "$out/$dump" ] || { echo "nodestro-server backup wrote no dump: $printed" >&2; exit 1; }

data="nodestro-data-$stamp.tar.gz"
docker compose run --rm --no-deps -T -v "$out:/backups" --entrypoint tar migrate \
  -C /var/lib/nodestro --exclude=./backups -czf "/backups/$data" .

image="$(docker compose config --format json | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["services"]["migrate"]["image"])')"
python3 -I - "$out" "$stamp" "$dump" "$data" "$storage" "$(docker image inspect --format '{{.Id}}' "$image")" <<'PY'
import hashlib, json, sys
from pathlib import Path

out, stamp, dump, data, storage, image = sys.argv[1:]


def entry(name: str) -> dict:
    path = Path(out) / name
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return {"name": name, "size": path.stat().st_size, "sha256": digest.hexdigest()}


manifest = {
    "format": 1,
    "created": stamp,
    "quiesced": True,  # API and worker were stopped for the whole backup
    "image": image,
    "database": entry(dump),
    "data": entry(data),
    "storage": entry(storage) if storage else None,
}
target = Path(out) / f"nodestro-backup-{stamp}.json"
target.write_text(json.dumps(manifest, indent=2) + "\n")
print(target)
PY
