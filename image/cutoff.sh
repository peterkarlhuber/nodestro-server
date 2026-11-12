#!/bin/sh
# Print the upload cutoff of the third-party packages for `pip install --uploaded-prior-to` (the studio's
# platform/uploaded-prior-to, shared by the studio's platform workflow, this image and the desktop backend).
# $1 is the interpreter whose pip installs: the studio's scripts/pip_cutoff.py checks the file and that this pip is
# 26.0 or newer, and fails the build otherwise. A studio commit from before the cutoff (studio.json pinned 6755c7a
# when this was written) prints nothing and a warning: the third-party packages are then not bound to a cutoff.
set -eu
python="${1:?cutoff.sh: the interpreter is required}"
if [ -f /src/platform/uploaded-prior-to ]; then
  "$python" -I /src/scripts/pip_cutoff.py
else
  echo "WARNING pip_cutoff: NOT USED, the studio $(cat /src/.studio-commit) has no platform/uploaded-prior-to;" \
    "the third-party packages are not bound to an upload cutoff" >&2
fi
