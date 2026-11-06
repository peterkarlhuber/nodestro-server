"""Acceptance tests of plan step PR-12: the server, end to end, as operators and browsers use it.

Every test drives the running stack from the outside (see conftest.py):

- an incomplete or unsafe configuration is refused before anything starts (``profile.invalid``);
- anonymous requests are refused, a login goes through the identity provider (Dex);
- a tenant never sees another tenant's data, and provider keys are stored encrypted;
- tool code (untrusted) runs only in a container of the sandbox daemon, never on the server's host, and not at
  all while that daemon is down; tenants reach only the model endpoints the operator allowed;
- a worker killed in the middle of a run leaves the run interrupted (not executed twice), and other workers go on;
- a suspended tenant is closed (sessions, logins, its runs) until it is resumed, and other tenants go on;
- a pg_dump backup restores the database; a paired backup (scripts/backup.sh) restores the database and the data
  volume of the same point in time;
- the live run chat (LRC-1): a question about a run in a worker is answered by the API process, an instruction
  stored by the API reaches the orchestrator in the worker at its next decision, and another tenant sees nothing;
- Amazon Bedrock without an operator role: a tenant cannot use it although the server's own processes have AWS
  credentials, and tool code never sees an AWS variable;
- run budget decisions (BUDGET-1): a run in the worker pauses before a request its budget cannot cover, a raise in
  the API process continues it in a worker, and the request is sent exactly once.
"""

from __future__ import annotations

import json
from pathlib import Path
import secrets
import subprocess
import tarfile
import tempfile
import threading
import time
from typing import Any

import httpx
import pytest

from conftest import (
    ALL_SWITCHES,
    ORIGIN,
    Browser,
    LoginRefused,
    Tenants,
    accounts,
    compose,
    login,
    new_tenant,
    operator,
    psql,
    wait_for,
    wait_healthy,
)

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


def test_the_database_has_pgvector_for_semantic_knowledge_search(stack: None) -> None:
    # Installed by the superuser (compose/postgres/roles.sql via db-roles): pgvector is not a trusted extension, so the
    # owner role could not install it in a migration. The runtime ranks vectors with it where it is installed.
    assert psql("SELECT extversion FROM pg_extension WHERE extname = 'vector'").strip() == "0.8.7"
    assert psql("SELECT '[1,2,3]'::vector <=> '[1,2,3]'::vector").strip() == "0"


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
    # NODESTRO_SECRETS_FORMAT=axs1 (compose/all-switches.yaml): Axentra's keyring format instead of v1.
    assert ("\taxs1.k1." if ALL_SWITCHES else "nodestro:enc:v1:") in dump


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
    # Tool code runs in Orkexa's containers (``orkexa-sandbox-*``) since the runtime uses Orkexa's run shape;
    # ``nodestro-sandbox-*`` are the runtime's own (dependency checks). Self-test containers are not counted.
    return [name for name in output.split() if name.startswith(("orkexa-sandbox-", "nodestro-sandbox-"))]


def _sandbox_approved(browser: Browser, timeout: float = 900) -> None:
    """Wait until the API's Docker monitor has passed the preflight and the in-container self-test.

    A fresh sandbox daemon first builds the sandbox image and runs the self-test in the background; until then the
    state is ``checking`` and tool code is refused with ``docker-checking`` (nothing runs without that proof)."""

    def approved() -> dict[str, Any] | None:
        answer = browser.get("/api/sandbox/status", params={"wait": 5}, timeout=60)
        assert answer.status_code == 200, answer.text
        body = dict(answer.json())
        assert body.get("state") in ("checking", "approved"), body  # the sandbox daemon must not be refused
        return body if body["state"] == "approved" else None

    wait_for(approved, timeout=timeout, every=1, what="the Docker sandbox check of the API")


def _finished_in_sandbox(browser: Browser, workflow_id: str, timeout: float = 900) -> dict[str, Any]:
    """A run of ``workflow_id``, started again while the worker's own Docker check is still running.

    Every process proves the daemon itself; a worker's check starts with its first job, so a tool call in a run can be
    refused with ``docker-checking`` for a while after the worker started. Any other result is returned as it is."""
    deadline = time.monotonic() + timeout
    while True:
        run = _finished(browser, _start(browser, workflow_id))
        if "docker-checking" not in json.dumps(run) or time.monotonic() > deadline:
            return run
        time.sleep(10)


def _save_tool(browser: Browser) -> None:
    _sandbox_approved(browser)
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
    run = _finished_in_sandbox(alice, _workflow(alice, _flow("Tool run", prompt, tools=["shout"])))
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
        _sandbox_approved(alice)  # the restarted daemon is proven again before later tests run tool code


# ---- Amazon Bedrock without an operator role -----------------------------------------------------

AWS_DECOY = "e2e-decoy-access-key-id"  # tests/e2e/aws-decoy.yaml: the server's own AWS credentials (not real ones)

#: A tool that keeps its container busy for a few seconds, so the test can read the container's environment.
#: Tool code cannot read environment variables itself (its static check refuses ``os``), so the test reads the
#: container's configuration on the sandbox daemon instead.
BUSY_TOOL = '''\
def busy(rounds: int) -> int:
    """Count for a while.

    Args:
        rounds: How many numbers to add up.

    Returns:
        The sum of the remainders.
    """
    total = 0
    for number in range(rounds):
        total += number % 7
    return total
'''

BUSY_TOOL_TESTS = """\
from tool import busy


def test_busy():
    assert busy(8) == 21
"""


def _server_has_aws_credentials() -> None:
    for service in ("api", "worker"):
        found = compose("exec", "-T", service, "printenv", "AWS_ACCESS_KEY_ID", check=False).stdout.strip()
        assert found == AWS_DECOY, f"{service}: scripts/e2e.sh layers tests/e2e/aws-decoy.yaml ({found!r})"


def test_bedrock_is_not_available_without_an_operator_role(tenants: Tenants) -> None:
    """The server's processes have AWS credentials and a region, but NODESTRO_BEDROCK_TENANT_ROLES assigns no role:
    a tenant can neither save Bedrock settings nor get a verified connection, and no AWS call is made."""
    _server_has_aws_credentials()
    _, owner = new_tenant("alice", "bedrock")
    bedrock = next(item for item in owner.get("/api/settings").json()["providers"] if item["id"] == "bedrock")
    assert bedrock["auth_methods"] == ["operator_role"] and bedrock["operator_role"] is False, bedrock
    assert bedrock["configured"] is False, bedrock
    assert bedrock["verification"]["code"] == "provider.bedrock_not_available", bedrock
    saved = owner.put("/api/settings", json={"providers": {"bedrock": {"region": "eu-central-1"}}})
    assert saved.status_code == 400 and saved.json()["code"] == "provider.bedrock_not_available", saved.text
    verified = owner.post("/api/settings/providers/bedrock/verify", json={})
    assert verified.status_code == 200, verified.text
    assert verified.json()["verification"] == {
        "state": "not_configured",
        "checked_at": None,  # nothing was checked against AWS
        "code": "provider.bedrock_not_available",
    }, verified.text
    # A run of a workflow with a Bedrock model is refused before it starts, so it never uses the server's credentials.
    flow = _workflow(owner, _flow("Bedrock without a role", "hello", model="bedrock:eu.anthropic.claude-sonnet-4-5"))
    refused = owner.post(f"/api/workflows/{flow}/runs", json={"input": "go"})
    assert refused.status_code == 400 and refused.json()["code"] == "provider.bedrock_not_available", refused.text


def _running_tool_container_env(browser: Browser, rounds: int) -> list[str] | None:
    """Call ``busy`` and read the environment of its container on the sandbox daemon while it runs (``None`` when the
    call ended before its container was seen)."""
    answer: dict[str, Any] = {}
    call = threading.Thread(
        target=lambda: answer.update(
            response=browser.post("/api/tools/busy/run", json={"input": {"rounds": rounds}}, timeout=600)
        )
    )
    call.start()
    found: list[str] | None = None
    try:
        while call.is_alive() and found is None:
            names = compose("exec", "-T", "sandbox", "docker", "ps", "--format", "{{.Names}}").stdout.split()
            for name in (item for item in names if item.startswith("orkexa-sandbox-")):
                inspected = compose(
                    "exec", "-T", "sandbox", "docker", "inspect", "--format", "{{json .Config.Env}}", name, check=False
                )
                if inspected.returncode == 0:
                    found = list(json.loads(inspected.stdout) or [])
                    break
            time.sleep(0.1)
    finally:
        call.join()
    response = answer["response"]
    assert response.status_code == 200 and response.json()["is_error"] is False, response.text
    return found


def test_tool_code_sees_no_aws_variables(tenants: Tenants) -> None:
    """The server's API process has AWS credentials; the container that runs a tool on the sandbox daemon gets none
    of its variables (Orkexa's run shape passes no ``-e``)."""
    _server_has_aws_credentials()
    alice = tenants.alice
    _sandbox_approved(alice)
    saved = alice.post(
        "/api/tools", json={"function_name": "busy", "code": BUSY_TOOL, "tests": BUSY_TOOL_TESTS}, timeout=900
    )
    assert saved.status_code in (200, 201) and saved.json()["tool"] is not None, saved.text
    rounds = 20_000_000
    env = None
    for _ in range(3):  # a fast machine may finish before the container is seen: count longer
        env = _running_tool_container_env(alice, rounds)
        if env is not None:
            break
        rounds *= 2
    assert env is not None, "no tool container was seen while the tool ran"
    assert not [item for item in env if item.upper().startswith("AWS_")], env


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


# ---- live run chat and steering (LRC-1) ----------------------------------------------------------


def test_the_live_run_chat_routes_in_the_image(tenants: Tenants) -> None:
    # Orchestrator decisions need structured output with reasoning effort, which the OpenAI-compatible stub cannot
    # serve; delivery from the API process to the worker is covered by the runtime's PostgreSQL tests. Here: the
    # routes, permissions and tenant isolation of the built image, and the event stream through the proxy chain.
    alice, bob = tenants.alice, tenants.bob
    _use_the_stub(alice)
    prompt = f"SLOW 15 {secrets.token_hex(4)}"
    run_id = _start(alice, _workflow(alice, _flow("Chat without a team leader", prompt)))
    wait_for(lambda: _stub_count(prompt) == 1, timeout=180, what="the model call")
    view = alice.get(f"/api/runs/{run_id}/chat")
    assert view.status_code == 200, view.text
    assert view.json()["active"] and view.json()["targets"] == [] and view.json()["messages"] == [], view.json()
    body = {"kind": "instruction", "target_run_id": run_id, "node_id": "a", "content": "Add a summary"}
    refused = alice.post(f"/api/runs/{run_id}/chat/messages", json=body)
    assert refused.status_code == 404 and refused.json()["code"] == "run_chat.unknown_target", refused.text
    assert bob.get(f"/api/runs/{run_id}/chat").status_code == 404  # another tenant
    assert bob.post(f"/api/runs/{run_id}/chat/messages", json=body).status_code in (403, 404)
    with alice.client.stream("GET", f"/api/runs/{run_id}/chat/events", timeout=30) as events:
        assert events.status_code == 200 and events.headers["content-type"].startswith("text/event-stream")
        first = next(events.iter_lines())
        assert first == "event: snapshot", first
    run = _finished(alice, run_id)
    assert run["status"] == "succeeded", run
    closed = alice.post(f"/api/runs/{run_id}/chat/messages", json={**body, "kind": "question", "content": "How?"})
    assert closed.status_code in (404, 409), closed.text


# ---- run budget decisions (BUDGET-1) -------------------------------------------------------------


def test_a_budget_decision_in_the_api_continues_the_run_in_the_worker(tenants: Tenants) -> None:
    """A run in the worker pauses before a request its budget cannot cover; the decision in the API process continues
    it in a worker, the request is sent exactly once, and another tenant sees nothing of it."""
    alice, bob = tenants.alice, tenants.bob
    _use_the_stub(alice)
    price = {"input_usd_per_mtok": "3", "output_usd_per_mtok": "15", "quality": "contract"}
    priced = alice.put("/api/pricing/overrides/compatible/stub-model", json=price)
    assert priced.status_code == 200, priced.text
    prompt = f"ECHO {secrets.token_hex(4)}"
    flow = {**_flow("Budget decision", prompt, max_tokens=1000), "budget_usd": 0.0001}
    run_id = _start(alice, _workflow(alice, flow), "budget")
    paused = wait_for(
        lambda: (run := _run(alice, run_id))["status"] == "paused" and run, timeout=180, every=1, what="the pause"
    )
    assert paused["nodes"]["a"]["status"] == "awaiting_budget", paused
    assert _stub_count(prompt) == 0  # nothing was sent
    view = alice.get(f"/api/runs/{run_id}/budget").json()
    pending = view["pending"]
    assert pending is not None and view["policy"]["can_decide"], view
    assert [item["id"] for item in alice.get("/api/budget-requests").json()] == [pending["id"]]
    assert bob.get(f"/api/runs/{run_id}/budget").status_code == 404
    assert bob.get("/api/budget-requests").json() == []
    body = {"request_id": pending["id"], "action": "raise", "limit_usd": "1.00", "idempotency_key": "e2e-1"}
    assert bob.post(f"/api/runs/{run_id}/budget/decisions", json=body).status_code == 404
    decided = alice.post(f"/api/runs/{run_id}/budget/decisions", json=body)
    assert decided.status_code == 200, decided.text
    run = _finished(alice, run_id, timeout=300)
    assert run["status"] == "succeeded" and run["output"] == "stub: budget", run
    assert run["budget"]["limit_usd"] == "1.00" and _stub_count(prompt) == 1
    workflow = alice.get(f"/api/workflows/{run['workflow_id']}").json()
    assert workflow["budget_usd"] == 0.0001  # the stored budget is unchanged
    assert alice.delete("/api/pricing/overrides/compatible/stub-model").status_code == 204


# ---- suspended tenants --------------------------------------------------------------------------------------------


def test_a_suspended_tenant_is_closed_until_it_is_resumed(tenants: Tenants) -> None:
    tenant, bob = new_tenant("bob", "initech")
    _use_the_stub(bob)
    prompt = f"SLOW 30 {secrets.token_hex(4)}"
    run_id = _start(bob, _workflow(bob, _flow("Cut off", prompt)))
    wait_for(lambda: _stub_count(prompt) == 1, timeout=180, what="the model call of the run")
    assert "suspended" in operator("suspend-tenant", tenant).stdout
    try:
        refused = bob.get("/api/auth/me")
        assert refused.status_code == 403 and refused.json()["code"] == "identity.tenant_suspended", refused.text
        with pytest.raises(LoginRefused) as login_refused:
            login(accounts()["bob"], tenant=tenant)
        assert login_refused.value.response.json()["code"] == "identity.tenant_suspended"
        switch = tenants.bob.post("/api/auth/switch", json={"tenant_id": tenant})
        assert switch.status_code == 403 and switch.json()["code"] == "identity.tenant_suspended", switch.text
        assert tenants.bob.get("/api/auth/me").json()["tenant_id"] == tenants.globex  # bob's other tenant goes on
        assert tenant not in tenants.bob.get("/api/auth/me").json()["tenants"]
        time.sleep(40)  # past the stub's answer: the worker stopped the run, so nothing of it is stored
    finally:
        assert "active" in operator("resume-tenant", tenant).stdout
    assert bob.get("/api/auth/me").json()["tenant_id"] == tenant  # the session works again
    run = _finished(bob, run_id, timeout=300)
    assert run["status"] == "failed", run  # interrupted, not finished behind the operator's back
    assert _stub_count(prompt) == 1


# ---- backup and restore -------------------------------------------------------------------------


def test_backup_and_restore_with_pg_dump(tenants: Tenants) -> None:
    alice = tenants.alice
    kept = _workflow(alice, _flow("Kept by the backup", "ALPHA"))
    if ALL_SWITCHES:  # an input file in Axentra's storage, so that the files archive has something to keep
        marker = "kept-file-" + secrets.token_hex(8)
        uploaded = alice.post("/api/inputs", files=[("files", (f"{marker}.txt", marker.encode(), "text/plain"))])
        assert uploaded.status_code == 201, uploaded.text
    with tempfile.TemporaryDirectory() as directory:
        Path(directory).chmod(0o777)  # the image's user (10001) writes the dump
        # As the owner role (the migrate service, NODESTRO_DATABASE_MIGRATION_URL), as docs/RUNBOOK.md says: the
        # runtime role cannot read every row of the tables with row-level security (Axentra's), so its pg_dump fails.
        result = compose(
            "run", "--rm", "--no-deps", "-T", "-v", f"{directory}:/backups", "migrate", "backup", "/backups"
        )
        printed = [Path(line).name for line in result.stdout.strip().splitlines()]
        written = Path(directory) / next(name for name in printed if name.endswith(".dump"))
        if ALL_SWITCHES:  # NODESTRO_FILES_BACKEND=axentra with a local directory: archived next to the dump
            archive = Path(directory) / next(name for name in printed if name.endswith(".tar.gz"))
            with tarfile.open(archive) as files:
                stored = [files.extractfile(item) for item in files.getmembers() if item.isfile()]
                assert any(marker.encode() == item.read() for item in stored if item), files.getnames()
        assert written.read_bytes().startswith(b"PGDMP")
        assert alice.delete(f"/api/workflows/{kept}").status_code == 204
        later = _workflow(alice, _flow("Written after the backup", "ALPHA"))
        # A schema of the owner role that the dump does not contain (another installation's NODESTRO_DATABASE_SCHEMA,
        # the operator's own tables): the restore drops the newer release's tables only in the dump's schemas.
        psql(
            "CREATE SCHEMA e2e_other AUTHORIZATION nodestro_owner; "
            "CREATE TABLE e2e_other.kept (id int); ALTER TABLE e2e_other.kept OWNER TO nodestro_owner"
        )
        restore = subprocess.run(
            ["bash", str(Path(__file__).resolve().parents[2] / "scripts" / "restore.sh"), str(written)],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        assert restore.returncode == 0, restore.stdout + restore.stderr
    try:
        assert psql("SELECT to_regclass('e2e_other.kept') IS NOT NULL").strip() == "t", "the restore dropped e2e_other"
    finally:
        psql("DROP SCHEMA IF EXISTS e2e_other CASCADE")
    wait_healthy("api")
    wait_healthy("worker")
    assert alice.get(f"/api/workflows/{kept}").json()["name"] == "Kept by the backup"
    assert alice.get(f"/api/workflows/{later}").status_code == 404


def _upload(browser: Browser, name: str, data: bytes) -> str:
    answer = browser.post("/api/inputs", files=[("files", (name, data, "text/plain"))])
    assert answer.status_code == 201, answer.text
    stored = answer.json()[0]
    assert stored["file"], stored
    return str(stored["file"]["id"])


def test_a_paired_backup_restores_the_database_and_the_tenant_files(tenants: Tenants) -> None:
    """scripts/backup.sh stops the API and the worker, dumps the database and archives the data volume at the same
    point in time; scripts/restore.sh with its manifest restores both, so a tenant's input file is back with its
    bytes and what was written later is gone from the database and the volume."""
    alice = tenants.alice
    kept_bytes = ("kept by the paired backup " + secrets.token_hex(8)).encode()
    kept = _upload(alice, "kept.txt", kept_bytes)
    flow = _workflow(alice, _flow("Kept by the paired backup", "ALPHA"))
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    with tempfile.TemporaryDirectory() as directory:
        made = subprocess.run(
            ["bash", str(scripts / "backup.sh"), directory], capture_output=True, text=True, check=False, timeout=600
        )
        assert made.returncode == 0, made.stdout + made.stderr
        manifest_path = Path(made.stdout.strip().splitlines()[-1])
        manifest = json.loads(manifest_path.read_text())
        assert manifest["quiesced"] is True and manifest["database"]["name"].endswith(".dump"), manifest
        with tarfile.open(manifest_path.parent / manifest["data"]["name"]) as archive:
            names = archive.getnames()
            assert not any(name.startswith("./backups/") for name in names), "pre-migration dumps are left out"
            stored = [archive.extractfile(item) for item in archive.getmembers() if item.isfile()]
            assert any(item is not None and item.read() == kept_bytes for item in stored), names
        # The API and the worker run again after the backup.
        wait_healthy("api")
        wait_healthy("worker")
        assert alice.delete(f"/api/inputs/{kept}").status_code == 204
        assert alice.get(f"/api/inputs/{kept}").status_code == 404
        later = _upload(alice, "later.txt", b"written after the backup")

        # A file whose checksum does not match the manifest: nothing is restored.
        data_archive = manifest_path.parent / manifest["data"]["name"]
        original = data_archive.read_bytes()
        data_archive.write_bytes(original + b"x")
        refused = subprocess.run(
            ["bash", str(scripts / "restore.sh"), str(manifest_path)], capture_output=True, text=True, check=False
        )
        assert refused.returncode != 0 and "does not match the manifest" in refused.stderr, refused.stderr
        assert alice.get(f"/api/inputs/{later}").status_code == 200, "a refused restore changed nothing"
        data_archive.write_bytes(original)

        restore = subprocess.run(
            ["bash", str(scripts / "restore.sh"), str(manifest_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        assert restore.returncode == 0, restore.stdout + restore.stderr
    wait_healthy("api")
    wait_healthy("worker")
    content = alice.get(f"/api/inputs/{kept}/content")
    assert content.status_code == 200 and content.content == kept_bytes, content.text[:200]
    assert alice.get(f"/api/inputs/{later}").status_code == 404
    assert alice.get(f"/api/workflows/{flow}").json()["name"] == "Kept by the paired backup"
    # The later file's bytes are gone from the volume too, not only its row.
    blobs = compose("exec", "-T", "api", "grep", "-rl", "written after the backup", "/var/lib/nodestro", check=False)
    assert blobs.stdout.strip() == "", blobs.stdout
