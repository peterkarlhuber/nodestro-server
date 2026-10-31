#!/usr/bin/env bash
# Build the server image from the studio commit in studio.json (every component pinned by full commit SHA).
#
#   NODESTRO_READ=<token with read access to the component repositories> scripts/build-image.sh [TAG]
#
# The token reaches the build only as a BuildKit secret, never as an argument or a layer. Behind a
# TLS-inspecting proxy, NODESTRO_EXTRA_CA_FILE names its certificate bundle (passed as the `build_ca` secret).
# NODESTRO_VERSION (default `dev`) becomes the image's version label; every image is labeled unsigned, and a version
# with a pre-release part (`v0.2.0-preview.1`) is labeled as a preview.
# Development only: NODESTRO_OVERRIDES=DIR replaces pinned components with the wheels in DIR; such an image says so
# in /opt/nodestro/overridden.txt and is tagged `*-dev` (a release tag is refused).
# NODESTRO_TARGET=local builds the Nodestro Local Docker target of the same definition instead (a check here; that
# product is built and tested by nodestro-local-docker).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tag="${1:-nodestro-server:dev}"
commit="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["nodestro-studio"])' "$root/studio.json")"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "studio.json must name a full commit SHA" >&2; exit 1; }
args=(--file "$root/image/Dockerfile" --build-arg "STUDIO_COMMIT=$commit" --tag "$tag" --load)
if [ -n "${NODESTRO_TARGET:-}" ]; then args+=(--target "$NODESTRO_TARGET"); fi
args+=(--label "org.opencontainers.image.source=https://github.com/peterkarlhuber/nodestro-server")
args+=(--label "org.opencontainers.image.revision=$(git -C "$root" rev-parse HEAD 2>/dev/null || echo unknown)")
args+=(--label "dev.nodestro.studio-commit=$commit")
version="${NODESTRO_VERSION:-dev}"
channel=release
if [[ "$version" == *-* || "$version" == dev ]]; then channel=preview; fi
args+=(--label "org.opencontainers.image.version=$version" --label "dev.nodestro.channel=$channel")
args+=(--label "dev.nodestro.signing=unsigned")
if [ -n "${NODESTRO_READ:-}" ]; then args+=(--secret "id=nodestro_read,env=NODESTRO_READ"); fi
if [ -n "${NODESTRO_EXTRA_CA_FILE:-}" ]; then args+=(--secret "id=build_ca,src=$NODESTRO_EXTRA_CA_FILE"); fi
if [ -n "${NODESTRO_BUILD_NETWORK:-}" ]; then args+=(--network "$NODESTRO_BUILD_NETWORK"); fi
for name in HTTPS_PROXY NO_PROXY; do
  if [ -n "${!name:-}" ]; then args+=(--build-arg "$name=${!name}"); fi
done
if [ -n "${NODESTRO_OVERRIDES:-}" ]; then
  [[ "$tag" == *-dev || "$tag" == *:dev ]] || { echo "an image with overrides must have a dev tag" >&2; exit 1; }
  args+=(--build-context "overrides=$NODESTRO_OVERRIDES")
fi
docker buildx build "${args[@]}" "$root"
