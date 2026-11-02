#!/usr/bin/env bash
# Start the development stack with a fresh state, run the end-to-end acceptance tests, and stop it again.
#
#   NODESTRO_IMAGE=nodestro-server:dev scripts/e2e.sh [pytest arguments]
#
# Needs Docker with compose, Python 3.10+ with pytest and httpx, and the image (scripts/build-image.sh). Behind a
# TLS-inspecting proxy, set NODESTRO_EXTRA_CA_FILE. KEEP_STACK=1 leaves the stack running afterwards.
# NODESTRO_E2E_ALL_SWITCHES=1 layers compose/all-switches.yaml (every Axentra migration switch on) and runs the tests
# of the switched-on paths too (tests/e2e/test_all_switches.py); without it those tests are skipped.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export COMPOSE_FILE="$root/compose/compose.yaml"
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
# How the sandbox daemon confines its containers (the self-test refuses unconfined ones on an AppArmor host).
docker compose exec -T sandbox sh -c '
  echo "container=${container:-}"; ls -l /sbin/apparmor_parser /usr/sbin/apparmor_parser 2>&1
  mountpoint /sys/kernel/security; ls /sys/kernel/security 2>&1; cat /sys/module/apparmor/parameters/enabled 2>&1
  cat /proc/self/attr/current 2>&1; grep -c docker-default /sys/kernel/security/apparmor/profiles 2>&1
  docker info --format "{{json .SecurityOptions}}"
  docker run --rm alpine:3.22 cat /proc/self/attr/current 2>&1
  cat /proc/self/attr/apparmor/current 2>&1; cat /sys/kernel/security/lsm; echo
  grep -E "docker-default|containerd|unconfined" /sys/kernel/security/apparmor/profiles 2>&1 | head
  id=$(docker create alpine:3.22 cat /proc/self/attr/apparmor/current)
  docker inspect --format "AppArmorProfile={{.AppArmorProfile}}" "$id"; docker start -a "$id"; docker rm "$id" >/dev/null
  docker run --rm --security-opt apparmor=docker-default alpine:3.22 cat /proc/self/attr/apparmor/current 2>&1
  runc --version 2>&1 | head -1; ps -o args= -p "$(pidof dockerd)"' || true
docker compose up -d --wait --wait-timeout 600 api worker
NODESTRO_E2E=1 python3 -m pytest -p no:cacheprovider tests/e2e "$@"
