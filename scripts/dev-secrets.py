#!/usr/bin/env python3
"""Write random secrets for the development compose file into compose/.secrets/ (once; existing files stay).

Creates the PostgreSQL password, the database URL, the OpenID Connect client secret, the server's secret key, the
Dex environment (client secret and the passwords of the development users alice, bob and mallory) and users.json
(the same passwords, for the end-to-end tests). The directory is readable only by its owner; the files inside are
readable by the containers' users. Nothing here is meant for production.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import secrets
import sys

USERS = ("alice", "bob", "mallory")


def main() -> int:
    root = Path(__file__).resolve().parent.parent / "compose" / ".secrets"
    root.mkdir(mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    port = os.environ.get("NODESTRO_DB_PORT", "55433")

    def write(name: str, value: str) -> None:
        path = root / name
        if path.exists():
            return
        path.write_text(value, encoding="utf-8")
        os.chmod(path, 0o644)  # the containers' users (postgres, 10001) read their secret files

    users_file = root / "users.json"
    users = (
        json.loads(users_file.read_text())
        if users_file.exists()
        else {name: {"email": f"{name}@example.com", "password": secrets.token_urlsafe(18)} for name in USERS}
    )
    database_password = (
        (root / "postgres_password").read_text().strip()
        if (root / "postgres_password").exists()
        else secrets.token_urlsafe(24)
    )
    client_secret = (
        (root / "oidc_client_secret").read_text().strip()
        if (root / "oidc_client_secret").exists()
        else secrets.token_urlsafe(32)
    )
    write("postgres_password", database_password + "\n")
    write("database_url", f"host=localhost port={port} user=nodestro dbname=nodestro password={database_password}\n")
    write("oidc_client_secret", client_secret + "\n")
    write("secret_key", base64.b64encode(secrets.token_bytes(32)).decode() + "\n")
    write("users.json", json.dumps(users, indent=2) + "\n")
    lines = [f"NODESTRO_OIDC_CLIENT_SECRET={client_secret}"]
    lines += [f"DEX_PASSWORD_{name.upper()}={users[name]['password']}" for name in USERS]
    write("dex.env", "\n".join(lines) + "\n")
    os.chmod(root / "dex.env", 0o600)
    print(f"secrets in {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
