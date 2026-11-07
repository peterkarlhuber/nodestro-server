#!/usr/bin/env bash
# Start the development stack behind Caddy as the TLS proxy (tests/e2e/tls-proxy.yaml), create a tenant and its setup
# link, run the Chromium test tests/e2e/browser.mjs against https://localhost:$NODESTRO_TLS_PORT, and stop the stack.
#
#   NODESTRO_IMAGE=nodestro-server:dev scripts/browser-e2e.sh
#
# Needs Docker with compose, Python 3.11+, the image (scripts/build-image.sh), Node.js 22+ and Playwright with
# Chromium (`npm install --no-save playwright@1.63.0 && npx playwright install chromium`; NODE_PATH must reach the
# package when it is not installed next to this repository). NODESTRO_TLS_PORT (default 8443) is Caddy's port on
# 127.0.0.1. Behind a TLS-inspecting proxy, set NODESTRO_EXTRA_CA_FILE. NODESTRO_BROWSER_SHOTS=DIR keeps a screenshot
# of the page that failed. KEEP_STACK=1 leaves the stack running afterwards. Uses the same compose project and ports
# as scripts/e2e.sh, so the two never run at the same time.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export COMPOSE_FILE="$root/compose/compose.yaml:$root/tests/e2e/tls-proxy.yaml"
if [ -n "${NODESTRO_EXTRA_CA_FILE:-}" ]; then COMPOSE_FILE="$COMPOSE_FILE:$root/compose/extra-ca.yaml"; fi
export NODESTRO_TLS_PORT="${NODESTRO_TLS_PORT:-8443}"
[[ "$NODESTRO_TLS_PORT" =~ ^[0-9]+$ ]] || { echo "NODESTRO_TLS_PORT must be a port number" >&2; exit 2; }
python3 scripts/dev-secrets.py
docker compose down -v --remove-orphans >/dev/null 2>&1 || true
work="$(mktemp -d)"
cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then docker compose logs --no-color --tail=200 api caddy dex migrate || true; fi
  if [ "${KEEP_STACK:-0}" != "1" ]; then docker compose down -v --remove-orphans || true; fi
  rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT
# The browser needs the API, Dex and the proxy; the API waits for the database, its migrations and the sandbox daemon.
docker compose up -d --wait --wait-timeout 600 api caddy
tenant="browser-$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
docker compose run --rm --no-deps -T api create-tenant "$tenant" "Browser test" >/dev/null
setup="$(docker compose run --rm --no-deps -T api setup-link "$tenant" | tail -n 1 | tr -d '\r')"
# Caddy's local authority; the caddy service is healthy once it exists (tests/e2e/tls-proxy.yaml).
docker compose exec -T caddy cat /data/caddy/pki/authorities/local/root.crt >"$work/caddy-root.crt"
NODESTRO_BROWSER_ORIGIN="https://localhost:$NODESTRO_TLS_PORT" \
  NODESTRO_BROWSER_CA="$work/caddy-root.crt" \
  NODESTRO_BROWSER_SETUP="$setup" \
  NODESTRO_BROWSER_TENANT="$tenant" \
  NODESTRO_BROWSER_USERS="$root/compose/.secrets/users.json" \
  node tests/e2e/browser.mjs
