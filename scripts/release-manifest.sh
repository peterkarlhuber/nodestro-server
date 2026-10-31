#!/usr/bin/env bash
# Write release-manifest.json and SHA256SUMS for a server image (plan M6), from inside the image itself, so the
# license inventory lists exactly the Python packages it contains.
#
#   scripts/release-manifest.sh IMAGE VERSION OUT_DIR [FILE_IN_OUT_DIR...]
#
# The manifest names the image by its ID (`docker image inspect --format '{{.Id}}'`), which stays the same when the
# saved image is loaded and pushed. Files named after OUT_DIR (the saved image) get a size and SHA-256 entry.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
image=$1 version=$2 out=$3
shift 3
mkdir -p "$out"
chmod 0777 "$out" # the image runs as user 10001
files=()
for file in "$@"; do files+=("/out/$(basename "$file")"); done
id="$(docker image inspect --format '{{.Id}}' "$image")"
docker run --rm --network none --read-only --user 10001:10001 \
  -v "$root/scripts/release_manifest.py:/release/release_manifest.py:ro" -v "$(cd "$out" && pwd):/out" \
  --entrypoint /opt/nodestro/venv/bin/python "$image" -I /release/release_manifest.py \
  --product nodestro-server --version "$version" --out /out --studio-meta /opt/nodestro/meta \
  --commit "$(git -C "$root" rev-parse HEAD)" --python /opt/nodestro/venv/bin/python \
  --platform linux-amd64 --image "nodestro-server@$id" "${files[@]}"
