"""Add the server extras of the components the studio pinned, at exactly the pinned commits.

``pip install <studio>`` installs nodestro-api and nodestro-runtime at the commits the studio pins, without the
extras a server needs (PostgreSQL, OpenID Connect, encryption). This installs ``nodestro-api[server]`` and
``nodestro-runtime[postgres]`` from the same commits:

- when the studio has a lock (``--platform DIR`` holds ``internal-server.txt``), the extras are named without a
  URL and ``pip install -r internal-server.txt`` fixes every internal package, including the server-only ones such
  as axentra, at the locked commits;
- older studio commits have no lock: the commits are read from the installed packages' ``direct_url.json``.

``--uploaded-prior-to CUTOFF`` (from image/cutoff.sh, the studio's shared cutoff) goes to pip unchanged, so the
server extras' third-party packages follow the same cutoff as the rest of the environment.
"""

from __future__ import annotations

import argparse
from importlib.metadata import distribution
import json
from pathlib import Path
import subprocess
import sys

EXTRAS = {"nodestro-api": "server", "nodestro-runtime": "postgres"}


def pinned(name: str, extra: str) -> str:
    found = json.loads(distribution(name).read_text("direct_url.json") or "{}")
    commit = found.get("vcs_info", {}).get("commit_id", "")
    url = found.get("url", "")
    if len(commit) != 40 or not url:
        raise SystemExit(f"{name} is not installed from a pinned commit: {found}")
    return f"{name}[{extra}] @ git+{url}@{commit}"


def requirements(platform: Path | None) -> list[str]:
    lock = platform / "internal-server.txt" if platform else None
    if lock and lock.is_file():
        return ["-r", str(lock), *(f"{name}[{extra}]" for name, extra in EXTRAS.items())]
    return [pinned(name, extra) for name, extra in EXTRAS.items()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--platform", type=Path, metavar="DIR", help="the studio's platform/ directory")
    parser.add_argument("--uploaded-prior-to", metavar="CUTOFF", help="pip's upload cutoff (the studio's)")
    args = parser.parse_args()
    cutoff = ["--uploaded-prior-to", args.uploaded_prior_to] if args.uploaded_prior_to else []
    found = requirements(args.platform)
    print(" ".join(found))
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", *cutoff, *found],
        check=True,
    )


if __name__ == "__main__":
    main()
