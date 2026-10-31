"""Add the server extras of the components the studio pinned, at exactly the pinned commits.

``pip install <studio>`` installs nodestro-api and nodestro-runtime at the commits the studio pins, without the
extras a server needs (PostgreSQL, OpenID Connect, encryption). This installs ``nodestro-api[server]`` and
``nodestro-runtime[postgres]`` from the same commits, read from the installed packages' ``direct_url.json``.
"""

from __future__ import annotations

from importlib.metadata import distribution
import json
import subprocess
import sys


def pinned(name: str, extra: str) -> str:
    found = json.loads(distribution(name).read_text("direct_url.json") or "{}")
    commit = found.get("vcs_info", {}).get("commit_id", "")
    url = found.get("url", "")
    if len(commit) != 40 or not url:
        raise SystemExit(f"{name} is not installed from a pinned commit: {found}")
    return f"{name}[{extra}] @ git+{url}@{commit}"


requirements = [pinned("nodestro-api", "server"), pinned("nodestro-runtime", "postgres")]
print("\n".join(requirements))
subprocess.run(
    [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", *requirements],
    check=True,
)
