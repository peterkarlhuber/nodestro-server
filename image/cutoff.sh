#!/bin/sh
# Print the upload cutoff of the third-party packages for `pip install --uploaded-prior-to` (the studio's
# platform/uploaded-prior-to, shared by the studio's platform workflow, this image and the desktop backend).
# $1 is the interpreter whose pip installs: the studio's scripts/pip_cutoff.py checks the file and that this pip is
# 26.0 or newer, and fails the build otherwise. A studio without platform/uploaded-prior-to fails the build too.
set -eu
python="${1:?cutoff.sh: the interpreter is required}"
if [ ! -f /src/platform/uploaded-prior-to ] || [ ! -f /src/scripts/pip_cutoff.py ]; then
  echo "cutoff.sh: FAIL, the studio $(cat /src/.studio-commit) has no platform/uploaded-prior-to or" \
    "scripts/pip_cutoff.py; pin a studio commit with the shared upload cutoff in studio.json" >&2
  exit 1
fi
"$python" -I /src/scripts/pip_cutoff.py
