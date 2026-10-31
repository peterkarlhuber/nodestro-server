"""Acceptance tests of plan step PR-12: the server, end to end, as operators and browsers use it.

Every test drives the running stack from the outside (see conftest.py):

- an incomplete or unsafe configuration is refused before anything starts (``profile.invalid``);
- anonymous requests are refused, a login goes through the identity provider (Dex);
- a tenant never sees another tenant's data, and provider keys are stored encrypted;
- tool code (untrusted) runs only in a container of the sandbox daemon, never on the server's host, and not at
  all while that daemon is down; tenants reach only the model endpoints the operator allowed;
- a worker killed in the middle of a run leaves the run interrupted (not executed twice), and other workers go on;
- a pg_dump backup restores the database.
"""

from __future__ import annotations

import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from typing import Any

import httpx
import pytest

from conftest import ORIGIN, Browser, LoginRefused, Tenants, accounts, compose, login, operator, wait_for, wait_healthy

MODEL = "compatible:stub-model"
STUB = "http://localhost:9100/v1"

TOOL = '''\
def shout(text: str) -> str:
    """Shout a text.

    Args:
        text: What to shout.

    Returns:
        The text in capitals with an exclamation mark.
    """
    return text.upper() + "!"
'''

TOOL_TESTS = """\
from tool import shout


def test_shout():
    assert shout("hi") == "HI!"
"""


def _flow(name: str, prompt: str, **agent: Any) -> dict[str, Any]:
    return {
        "name": name,
        "nodes": [
            {"id": "start", "type": "start"},
            {
                "id": "a",
                "type": "agent",
                "label": "A",
                "agent": {"name": "A", "system_prompt": prompt, "model": MODEL, "effort": None, **agent},
            },
            {"id": "out", "type": "output"},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "a"}, {"id": "e2", "source": "a", "target": "out"}],
    }


def _use_the_stub(browser: Browser, key: str = "stub-key") -> None:
    supported = {name: "supported" for name in ("tools", "streaming")}
    answer = browser.put(
        "/api/settings",
        json={"providers": {"compatible": {"base_url": STUB, "api_key": key, "capabilities": supported}}},
    )
    assert answer.status_code == 200, answer.text


def _workflow(browser: Browser, flow: dict[str, Any]) -> str:
    answer = browser.post("/api/workflows", json=flow)
    assert answer.status_code == 201, answer.text
    return str(answer.json()["id"])


def _start(browser: Browser, workflow_id: str, text: str = "go") -> str:
    answer = browser.post(f"/api/workflows/{workflow_id}/runs", json={"input": text})
    assert answer.status_code == 201, answer.text
    return str(answer.json()["id"])


def _run(browser: Browser, run_id: str) -> dict[str, Any]:
    answer = browser.get(f"/api/runs/{run_id}")
    assert answer.status_code == 200, answer.text
    return dict(answer.json())


def _finished(browser: Browser, run_id: str, timeout: float = 600) -> dict[str, Any]:
    return dict(
        wait_for(
            lambda: (run := _run(browser, run_id))["status"] in ("succeeded", "failed", "cancelled") and run,
            timeout=timeout,
            every=1,
            what=f"run {run_id} to finish",
        )
    )


def _error_code(body: dict[str, Any]) -> str | None:
    code = body.get("error_code")
    return str(code) if code else None


def _stub_count(prompt: str) -> int:
    counts = httpx.get("http://localhost:9100/stats", timeout=10).json()
    return int(counts.get(prompt, 0))


# ---- configuration ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "fields"),
    [
        ({"NODESTRO_OIDC_ISSUER": "", "NODESTRO_SECRET_KEY_FILE": ""}, ["NODESTRO_OIDC_ISSUER", "NODESTRO_SECRET_KEY"]),
        ({"NODESTRO_PUBLIC_ORIGIN": "http://studio.example.com"}, ["NODESTRO_PUBLIC_ORIGIN"]),
        ({"NODESTRO_OIDC_ISSUER": "http://login.example.com"}, ["NODESTRO_OIDC_ISSUER"]),
        ({"NODESTRO_PROFILE": "desktop"}, ["NODESTRO_PROFILE"]),
    ],
)
def test_an_incomplete_or_unsafe_configuration_is_refused(
    stack: None, changes: dict[str, str], fields: list[str]
) -> None:
    for command in ("check", "api", "worker"):
        result = operator(command, check=False, env=changes)
        assert result.returncode != 0, result.stdout
        assert "profile.invalid" in result.stderr, result.stderr
        for name in fields:
            assert name in result.stderr, result.stderr
    secret_key = (Path(__file__).resolve().parents[2] / "compose" / ".secrets" / "secret_key").read_text().strip()
    result = operator("check", check=False, env={"NODESTRO_SECRET_KEY": secret_key})  # both forms at once
    assert result.returncode != 0 and "profile.invalid" in result.stderr
    assert secret_key not in result.stderr + result.stdout


def test_the_configured_server_is_ready(stack: None) -> None:
    result = operator("check")
    assert result.stdout.strip().endswith("ready"), result.stdout + result.stderr


# ---- authentication -----------------------------------------------------------------------------


def test_anonymous_requests_are_refused(stack: None) -> None:
    anonymous = Browser(None)
    forged = Browser("not-a-session")
    for browser in (anonymous, forged):
        for path in ("/api/auth/me", "/api/workflows", "/api/runs", "/api/settings", "/api/tools", "/api/knowledge"):
            answer = browser.get(path)
            assert answer.status_code == 401, (path, answer.status_code, answer.text)
        answer = browser.post("/api/workflows", json=_flow("Anonymous", "x"))
        assert answer.status_code in (401, 403), answer.text
        answer = browser.post("/api/tools/check", json={"function_name": "shout", "code": TOOL, "tests": TOOL_TESTS})
        assert answer.status_code in (401, 403), answer.text
    page = httpx.get(f"{ORIGIN}/", timeout=30)
    assert page.status_code == 200 and "<html" in page.text.lower()  # the studio's page itself is public
    assert httpx.get(f"{ORIGIN}/api/health", timeout=30).status_code == 200


def test_login_through_the_identity_provider(tenants: Tenants) -> None:
    me = tenants.alice.get("/api/auth/me")
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["tenant_id"] == tenants.acme and body["role"] == "owner" and body["email"] == "alice@example.com"
    assert body["tenants"] == {tenants.acme: "owner"}
    again = login(accounts()["alice"])  # a later login needs no setup link
    assert again.get("/api/auth/me").json()["tenant_id"] == tenants.acme
    assert again.post("/api/auth/logout").status_code == 204
    assert again.get("/api/auth/me").status_code == 401  # the session ended on the server


def test_a_wrong_password_or_an_account_without_tenant_gets_no_session(tenants: Tenants) -> None:
    with pytest.raises(LoginRefused):
        login(accounts()["alice"], password="wrong-" + secrets.token_hex(4))
    with pytest.raises(LoginRefused) as refused:
        login(accounts()["mallory"])
    assert refused.value.response.status_code == 403
    assert refused.value.response.json()["code"] == "identity.no_tenant"
    with pytest.raises(LoginRefused) as reused:  # an unknown setup link binds nobody
        login(accounts()["mallory"], setup="x" * 43)
    assert reused.value.response.json()["code"] == "identity.bootstrap_invalid"


def test_changing_requests_from_another_origin_are_refused(tenants: Tenants) -> None:
    answer = tenants.alice.client.post(
        "/api/workflows", json=_flow("Cross-site", "x"), headers={"Origin": "https://evil.example"}
    )
    assert answer.status_code == 403, answer.text


# ---- tenants ------------------------------------------------------------------------------------


def test_tenants_never_see_each_others_data(tenants: Tenants) -> None:
    alice, bob = tenants.alice, tenants.bob
    workflow_id = _workflow(alice, _flow("Acme secret flow", "ALPHA"))
    assert bob.get(f"/api/workflows/{workflow_id}").status_code == 404
    assert workflow_id not in json.dumps(bob.get("/api/workflows").json())
    assert bob.put(f"/api/workflows/{workflow_id}", json=_flow("Taken over", "x")).status_code in (403, 404)
    assert bob.delete(f"/api/workflows/{workflow_id}").status_code in (403, 404)
    assert bob.post(f"/api/workflows/{workflow_id}/runs", json={"input": "go"}).status_code in (403, 404)
    switch = bob.post("/api/auth/switch", json={"tenant_id": tenants.acme})
    assert switch.status_code == 404 and switch.json()["code"] == "identity.not_a_member"
    assert alice.get(f"/api/workflows/{workflow_id}").json()["name"] == "Acme secret flow"  # untouched

    marker = "sk-acme-" + secrets.token_hex(12)
    _use_the_stub(alice, key=marker)
    assert marker not in alice.get("/api/settings").text  # never shown again
    assert marker not in bob.get("/api/settings").text
    dump = compose("exec", "-T", "postgres", "pg_dump", "-U", "nodestro", "--data-only", "nodestro").stdout
    assert marker not in dump  # encrypted at rest
    assert "nodestro:enc:v1:" in dump


def test_tenants_use_only_the_model_endpoints_the_operator_allowed(tenants: Tenants) -> None:
    for url in ("http://169.254.169.254/latest", "http://localhost:5432/v1", "https://api.example.com/v1"):
        answer = tenants.bob.put("/api/settings", json={"providers": {"compatible": {"base_url": url}}})
        assert answer.status_code >= 400, (url, answer.text)
        assert answer.json().get("code") == "provider.endpoint_not_allowed", answer.text


# ---- the sandbox --------------------------------------------------------------------------------


def _sandbox_containers(since: float, *, host: bool = False) -> list[str]:
    """Names of the tool containers started since ``since`` on the sandbox daemon (or on the host's daemon)."""
    events = ["docker", "events", "--since", f"{since:.0f}", "--until", f"{time.time() + 1:.0f}"]
    events += ["--filter", "type=container", "--filter", "event=start", "--format", "{{.Actor.Attributes.name}}"]
    if host:
        output = subprocess.run(events, capture_output=True, text=True, check=True, timeout=60).stdout
    else:
        output = compose("exec", "-T", "sandbox", *events).stdout
    return [name for name in output.split() if name.startswith("nodestro-sandbox-")]


def _save_tool(browser: Browser) -> None:
    saved = browser.post("/api/tools", json={"function_name": "shout", "code": TOOL, "tests": TOOL_TESTS}, timeout=900)
    assert saved.status_code in (200, 201), saved.text
    assert saved.json()["tool"] is not None, saved.text  # its tests passed (in the sandbox)


def test_tool_code_runs_only_in_a_container_of_the_sandbox_daemon(tenants: Tenants) -> None:
    alice = tenants.alice
    since = time.time() - 1
    _save_tool(alice)
    direct = alice.post("/api/tools/shout/run", json={"input": {"text": "direct"}}, timeout=600)
    assert direct.status_code == 200, direct.text
    assert direct.json() == {"output": "DIRECT!", "is_error": False}, direct.text
    # In a run, executed by a worker: the agent (the model stub) calls the tool.
    _use_the_stub(alice)
    prompt = f"CALL shout {json.dumps({'text': 'in a run'})}"
    run = _finished(alice, _start(alice, _workflow(alice, _flow("Tool run", prompt, tools=["shout"]))))
    assert run["status"] == "succeeded", run
    assert run["output"] == "tool said: IN A RUN!", run
    # Tests, the direct call and the run each started containers on the sandbox daemon, none on the host's.
    assert len(_sandbox_containers(since)) >= 3, _sandbox_containers(since)
    assert _sandbox_containers(since, host=True) == []
    images = compose("exec", "-T", "sandbox", "docker", "images", "--format", "{{.Repository}}").stdout.split()
    assert "nodestro-env" in images  # the tool image was built inside the sandbox daemon


def test_without_the_sandbox_daemon_tool_code_does_not_run_at_all(tenants: Tenants) -> None:
    alice = tenants.alice
    if "shout" not in alice.get("/api/tools").text:
        _save_tool(alice)
    since = time.time() - 1
    compose("stop", "sandbox")
    try:
        answer = alice.post("/api/tools/shout/run", json={"input": {"text": "no daemon"}}, timeout=120)
        body = answer.json()
        assert answer.status_code >= 400 or body.get("is_error") is True, body
        assert "NO DAEMON!" not in json.dumps(body)  # nothing ran: no fallback to the host
        assert _sandbox_containers(since, host=True) == []
        refused = operator("check", check=False)
        assert refused.returncode != 0 and "sandbox.unavailable" in refused.stderr, refused.stderr
    finally:
        compose("start", "sandbox")
        wait_healthy("sandbox")


# ---- workers ------------------------------------------------------------------------------------


def test_a_worker_killed_in_the_middle_of_a_run(tenants: Tenants) -> None:
    alice = tenants.alice
    _use_the_stub(alice)
    prompt = f"SLOW 45 {secrets.token_hex(4)}"
    run_id = _start(alice, _workflow(alice, _flow("Long run", prompt)))
    wait_for(lambda: _stub_count(prompt) == 1, timeout=180, what="the model call of the long run")
    assert _run(alice, run_id)["status"] == "running"
    compose("kill", "-s", "SIGKILL", "worker")
    compose("up", "-d", "--no-deps", "worker")
    run = _finished(alice, run_id, timeout=300)  # the new worker reaps the expired lease
    assert run["status"] == "failed" and _error_code(run) == "run.interrupted", run
    time.sleep(5)
    assert _stub_count(prompt) == 1  # never executed a second time by itself
    after = _finished(alice, _start(alice, _workflow(alice, _flow("After the kill", "ECHO")), "still here"))
    assert after["status"] == "succeeded" and after["output"] == "stub: still here", after


# ---- backup and restore -------------------------------------------------------------------------


def test_backup_and_restore_with_pg_dump(tenants: Tenants) -> None:
    alice = tenants.alice
    kept = _workflow(alice, _flow("Kept by the backup", "ALPHA"))
    with tempfile.TemporaryDirectory() as directory:
        Path(directory).chmod(0o777)  # the image's user (10001) writes the dump
        result = compose("run", "--rm", "--no-deps", "-T", "-v", f"{directory}:/backups", "api", "backup", "/backups")
        written = Path(directory) / Path(result.stdout.strip().splitlines()[-1]).name
        assert written.read_bytes().startswith(b"PGDMP")
        assert alice.delete(f"/api/workflows/{kept}").status_code == 204
        later = _workflow(alice, _flow("Written after the backup", "ALPHA"))
        restore = subprocess.run(
            ["bash", str(Path(__file__).resolve().parents[2] / "scripts" / "restore.sh"), str(written)],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        assert restore.returncode == 0, restore.stdout + restore.stderr
    wait_healthy("api")
    wait_healthy("worker")
    assert alice.get(f"/api/workflows/{kept}").json()["name"] == "Kept by the backup"
    assert alice.get(f"/api/workflows/{later}").status_code == 404
