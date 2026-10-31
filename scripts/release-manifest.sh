#!/usr/bin/env bash
# Write release-manifest.json and SHA256SUMS for a server image (plan M6), from inside the image itself, so the
# license inventory lists exactly the Python packages it contains.
#
#   scripts/release-manifest.sh IMAGE VERSION OUT_DIR [PUBLISHED_REF@sha256:DIGEST]
#
# Without a published reference (a dry run) the manifest names the local image ID and says it is not published.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
image=$1 version=$2 out=$3 published=${4:-}
mkdir -p "$out"
chmod 0777 "$out" # the image runs as user 10001
if [ -z "$published" ]; then
  published="$image@$(docker image inspect --format '{{.Id}}' "$image") (local image ID, not published)"
fi
docker run --rm --network none --read-only --user 10001:10001 \
  -v "$root/scripts/release_manifest.py:/release/release_manifest.py:ro" -v "$(cd "$out" && pwd):/out" \
  --entrypoint /opt/nodestro/venv/bin/python "$image" -I /release/release_manifest.py \
  --product nodestro-server --version "$version" --out /out --studio-meta /opt/nodestro/meta \
  --commit "$(git -C "$root" rev-parse HEAD)" --python /opt/nodestro/venv/bin/python \
  --platform linux-amd64 --image "$published"
