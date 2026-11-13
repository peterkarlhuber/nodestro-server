"""Add the server extras of the components the studio pinned, at exactly the locked commits.

``pip install -r internal.txt <studio>`` installs nodestro-api and nodestro-runtime at the commits of the studio's
lock, without the extras a server needs (PostgreSQL, OpenID Connect, encryption). This installs
``nodestro-api[server]`` and ``nodestro-runtime[postgres]``: the extras are named without a URL and
``pip install -r <platform>/internal-server.txt`` (the studio's lock, server profile) fixes every internal package,
including the server-only ones such as axentra, at the locked commits. ``--platform DIR`` (the studio's
``platform/`` directory) is required; a studio without ``internal-server.txt`` fails the build.

``--uploaded-prior-to CUTOFF`` (required; from image/cutoff.sh, the studio's shared cutoff) goes to pip unchanged,
so the server extras' third-party packages follow the same cutoff as the rest of the environment.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

EXTRAS = {"nodestro-api": "server", "nodestro-runtime": "postgres"}


def requirements(platform: Path) -> list[str]:
    lock = platform / "internal-server.txt"
    if not lock.is_file():
        raise SystemExit(
            f"install.py: {lock} is missing: the studio has no lock of its internal packages (server profile); "
            "pin a studio commit with platform/internal-server.txt in studio.json"
        )
    return ["-r", str(lock), *(f"{name}[{extra}]" for name, extra in EXTRAS.items())]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--platform", type=Path, metavar="DIR", required=True, help="the studio's platform/ directory")
    parser.add_argument(
        "--uploaded-prior-to", metavar="CUTOFF", required=True, help="pip's upload cutoff (the studio's)"
    )
    args = parser.parse_args()
    found = requirements(args.platform)
    print(" ".join(found))
    cutoff = ["--uploaded-prior-to", args.uploaded_prior_to]
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", *cutoff, *found],
        check=True,
    )


if __name__ == "__main__":
    main()
