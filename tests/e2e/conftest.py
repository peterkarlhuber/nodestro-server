"""The end-to-end tests drive a running development stack (compose/compose.yaml) from the outside.

They need the stack up (``scripts/e2e.sh`` starts it, runs them and stops it) and talk to it like a browser and an
operator would: HTTP on http://localhost:8080, logins through Dex, and ``docker compose`` for operator commands.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any
from urllib.parse import urljoin
import uuid

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "compose" / "compose.yaml"
# COMPOSE_FILE may add override files (scripts/e2e.sh: compose/extra-ca.yaml behind a TLS-inspecting proxy).
os.environ.setdefault("COMPOSE_FILE", str(COMPOSE_FILE))
ORIGIN = "http://localhost:8080"
SESSION_COOKIE = "__Host-nodestro-session"
LOGIN_COOKIE = "__Host-nodestro-login"


def compose(
    *args: str, check: bool = True, timeout: float = 600, stdin: bytes | None = None
) -> subprocess.CompletedProcess[str]:
    """``docker compose`` on the development stack; output as text."""
    command = ["docker", "compose", *args]
    if stdin is not None:
        completed = subprocess.run(command, input=stdin, capture_output=True, timeout=timeout, check=False)
        result = subprocess.CompletedProcess(
            command,
            completed.returncode,
            completed.stdout.decode(errors="replace"),
            completed.stderr.decode(errors="replace"),
        )
    else:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if check and result.returncode != 0:
        raise AssertionError(f"{' '.join(args)} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return result


def operator(*args: str, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """``nodestro-server ARGS`` in a one-off container of the server image, configured like the API."""
    flags: list[str] = []
    for key, value in (env or {}).items():
        flags += ["-e", f"{key}={value}"]
    return compose("run", "--rm", "--no-deps", "-T", *flags, "api", *args, check=check)


def wait_for(probe: Any, *, timeout: float = 120, every: float = 0.5, what: str = "condition") -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = probe()
        if last:
            return last
        time.sleep(every)
    raise AssertionError(f"timed out waiting for {what} (last: {last!r})")


def wait_healthy(service: str, timeout: float = 180) -> None:
    def healthy() -> bool:
        ids = compose("ps", "-q", service, check=False).stdout.split()
        if not ids:
            return False
        state = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", ids[0]], capture_output=True, text=True, check=False
        )
        return state.stdout.strip() == "healthy"

    wait_for(healthy, timeout=timeout, every=1, what=f"{service} to be healthy")


@dataclass
class Account:
    name: str
    email: str
    password: str


def accounts() -> dict[str, Account]:
    users = json.loads((ROOT / "compose" / ".secrets" / "users.json").read_text())
    return {name: Account(name, item["email"], item["password"]) for name, item in users.items()}


class LoginRefused(Exception):
    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"{response.status_code}: {response.text[:300]}")
        self.response = response


def login(
    account: Account, *, setup: str | None = None, tenant: str | None = None, password: str | None = None
) -> Browser:
    """A browser session after logging in at Dex with the account's password (``LoginRefused`` otherwise)."""
    params = {key: value for key, value in (("setup", setup), ("tenant", tenant)) if value}
    with httpx.Client(follow_redirects=False, timeout=30) as http:
        answer = http.get(f"{ORIGIN}/api/auth/login", params=params)
        assert answer.status_code == 303, answer.text
        # The login cookie binds the callback to this browser. It is Secure; browsers send it to
        # http://localhost (a secure context), but httpx does not, so carry it over by hand.
        found = re.search(rf"{re.escape(LOGIN_COOKIE)}=([^;]+)", answer.headers.get("set-cookie", ""))
        assert found, answer.headers
        login_cookie = found.group(1)
        url = answer.headers["location"]
        assert url.startswith("http://localhost:5556/dex/"), url
        # Dex: authorization request -> the password connector's login form.
        for _ in range(10):
            answer = http.get(url)
            if answer.status_code not in (302, 303):
                break
            url = urljoin(url, answer.headers["location"])
        assert answer.status_code == 200 and 'name="password"' in answer.text, answer.text[:500]
        action = re.search(r'<form[^>]*action="([^"]*)"', answer.text)
        target = urljoin(url, action.group(1).replace("&amp;", "&")) if action and action.group(1) else url
        answer = http.post(target, data={"login": account.email, "password": password or account.password})
        for _ in range(10):
            if answer.status_code not in (302, 303):
                raise LoginRefused(answer)
            url = urljoin(str(answer.url), answer.headers["location"])
            if url.startswith(f"{ORIGIN}/"):
                break
            answer = http.get(url)
        callback = http.get(url, headers={"Cookie": f"{LOGIN_COOKIE}={login_cookie}"})
        if callback.status_code != 303:
            raise LoginRefused(callback)
        token = callback.cookies.get(SESSION_COOKIE)
        if not token:  # httpx keeps Secure cookies out of its jar for http://; read the header
            found = re.search(rf"{re.escape(SESSION_COOKIE)}=([^;]+)", callback.headers.get("set-cookie", ""))
            token = found.group(1) if found else None
        assert token, callback.headers
        cookie_header = callback.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie_header and "Secure" in cookie_header and "SameSite=lax" in cookie_header
    return Browser(token)


@dataclass
class Browser:
    """A logged-in browser: the session cookie and the studio's Origin on every request."""

    token: str | None
    client: httpx.Client = field(init=False)

    def __post_init__(self) -> None:
        headers = {"Origin": ORIGIN}
        if self.token:
            headers["Cookie"] = f"{SESSION_COOKIE}={self.token}"
        self.client = httpx.Client(base_url=ORIGIN, headers=headers, timeout=60, follow_redirects=False)

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.get(path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.post(path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.put(path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.delete(path, **kwargs)


@dataclass
class Tenants:
    acme: str
    globex: str
    alice: Browser
    bob: Browser


@pytest.fixture(scope="session")
def stack() -> None:
    if os.environ.get("NODESTRO_E2E") != "1":
        pytest.skip("NODESTRO_E2E=1 is not set (scripts/e2e.sh runs these tests against a started stack)")
    for service in ("postgres", "dex", "sandbox", "model-stub", "api", "worker"):
        wait_healthy(service)


@pytest.fixture(scope="session")
def tenants(stack: None) -> Iterator[Tenants]:
    """Two tenants, each with its first owner bound through a setup link: alice (acme) and bob (globex)."""
    suffix = uuid.uuid4().hex[:8]
    people = accounts()
    browsers = {}
    names = {"alice": f"acme-{suffix}", "bob": f"globex-{suffix}"}
    for person, tenant in names.items():
        operator("create-tenant", tenant, tenant.title())
        link = operator("setup-link", tenant).stdout.strip().splitlines()[-1]
        assert link.startswith(f"{ORIGIN}/api/auth/login?setup="), link
        browsers[person] = login(people[person], setup=link.split("setup=", 1)[1])
    yield Tenants(acme=names["alice"], globex=names["bob"], alice=browsers["alice"], bob=browsers["bob"])
