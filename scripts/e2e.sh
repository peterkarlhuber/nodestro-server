#!/usr/bin/env bash
# Start the development stack with a fresh state, run the end-to-end acceptance tests, and stop it again.
#
#   NODESTRO_IMAGE=nodestro-server:dev scripts/e2e.sh [pytest arguments]
#
# Needs Docker with compose, Python 3.11+ with pytest and httpx, and the image (scripts/build-image.sh). Behind a
# TLS-inspecting proxy, set NODESTRO_EXTRA_CA_FILE. KEEP_STACK=1 leaves the stack running afterwards.
# NODESTRO_E2E_ALL_SWITCHES=1 layers compose/all-switches.yaml (every Axentra migration switch on) and runs the tests
# of the switched-on paths too (tests/e2e/test_all_switches.py); without it those tests are skipped.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
# tests/e2e/aws-decoy.yaml: the server's processes get AWS credentials that tenants and tool code must never see.
export COMPOSE_FILE="$root/compose/compose.yaml:$root/tests/e2e/aws-decoy.yaml"
if [ -n "${NODESTRO_EXTRA_CA_FILE:-}" ]; then COMPOSE_FILE="$COMPOSE_FILE:$root/compose/extra-ca.yaml"; fi
export NODESTRO_E2E_ALL_SWITCHES="${NODESTRO_E2E_ALL_SWITCHES:-0}"
case "$NODESTRO_E2E_ALL_SWITCHES" in
  1) COMPOSE_FILE="$COMPOSE_FILE:$root/compose/all-switches.yaml" ;;
  0) ;;
  *) echo "NODESTRO_E2E_ALL_SWITCHES must be 0 or 1" >&2; exit 2 ;;
esac
# Short leases, so the test of a killed worker does not wait a minute.
export NODESTRO_WORKER_LEASE_SECONDS="${NODESTRO_WORKER_LEASE_SECONDS:-10}"
export NODESTRO_WORKER_REAP_SECONDS="${NODESTRO_WORKER_REAP_SECONDS:-2}"
python3 scripts/dev-secrets.py
docker compose down -v --remove-orphans >/dev/null 2>&1 || true
cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then docker compose logs --no-color --tail=200 api worker migrate sandbox dex || true; fi
  if [ "${KEEP_STACK:-0}" != "1" ]; then docker compose down -v --remove-orphans || true; fi
  exit "$status"
}
trap cleanup EXIT
docker compose up -d --wait --wait-timeout 600 postgres dex sandbox model-stub
docker compose up -d --wait --wait-timeout 600 api worker
NODESTRO_E2E=1 python3 -m pytest -p no:cacheprovider tests/e2e "$@"
