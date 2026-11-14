#!/bin/sh
# Finish a Python environment of image/Dockerfile: development overrides (if any), the consistency check against the
# studio's platform/versions.json ($2: the profile, server or studio), the pip freeze, no pip, no byte code, and an
# import check ($1).
set -eu
profile="${2:?finalize.sh: the profile (server or studio) is required}"
overridden=""
if ls /overrides/*.whl >/dev/null 2>&1; then
  echo "development build: replacing pinned components with $(ls /overrides)"
  /opt/nodestro/venv/bin/pip install --no-deps --force-reinstall --no-cache-dir --disable-pip-version-check /overrides/*.whl
  echo "development build" > /opt/nodestro/overridden.txt
  overridden=1
fi
# Every component at exactly the repository, commit and version the studio pins (scripts/lock_check.py of the same
# studio checkout, offline). A red check fails the build, except in a development build, whose overrides differ from
# the pins on purpose. A studio without scripts/lock_check.py fails the build.
if [ ! -f /src/scripts/lock_check.py ]; then
  echo "finalize.sh: FAIL, the studio $(cat /src/.studio-commit) has no scripts/lock_check.py;" \
    "pin a studio commit with the lock check in studio.json" >&2
  exit 1
fi
# The check's output stays in the image (/opt/nodestro/lock-check.txt): CI asserts that it covers tabrion (TABRION
# DC-SV-1), so a component that silently left versions.json, and thereby the check, is noticed.
if /opt/nodestro/venv/bin/python -I /src/scripts/lock_check.py --profile "$profile" \
  --versions /src/platform/versions.json > /opt/nodestro/lock-check.txt 2>&1; then
  cat /opt/nodestro/lock-check.txt
elif [ -n "$overridden" ]; then
  cat /opt/nodestro/lock-check.txt
  echo "development build: the overridden components differ from platform/versions.json (expected)"
else
  cat /opt/nodestro/lock-check.txt
  exit 1
fi
/opt/nodestro/venv/bin/pip freeze --disable-pip-version-check > /opt/nodestro/pinned.txt
/opt/nodestro/venv/bin/pip uninstall --yes --disable-pip-version-check pip
find /opt/nodestro/venv -type d -name __pycache__ -prune -exec rm -rf {} +
/opt/nodestro/venv/bin/python -I -c "$1"
