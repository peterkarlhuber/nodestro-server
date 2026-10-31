#!/bin/sh
# Finish a Python environment of image/Dockerfile: development overrides (if any), the pip freeze, no pip, no byte
# code, and an import check ($1).
set -eu
if ls /overrides/*.whl >/dev/null 2>&1; then
  echo "development build: replacing pinned components with $(ls /overrides)"
  /opt/nodestro/venv/bin/pip install --no-deps --force-reinstall --no-cache-dir --disable-pip-version-check /overrides/*.whl
  echo "development build" > /opt/nodestro/overridden.txt
fi
/opt/nodestro/venv/bin/pip freeze --disable-pip-version-check > /opt/nodestro/pinned.txt
/opt/nodestro/venv/bin/pip uninstall --yes --disable-pip-version-check pip
find /opt/nodestro/venv -type d -name __pycache__ -prune -exec rm -rf {} +
/opt/nodestro/venv/bin/python -I -c "$1"
