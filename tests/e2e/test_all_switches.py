"""Acceptance tests of the Axentra migration switches, all on (compose/all-switches.yaml).

``NODESTRO_E2E_ALL_SWITCHES=1 scripts/e2e.sh`` layers the override and runs these next to test_acceptance.py (which
must pass unchanged with every switch on); without it they are skipped. They check, from the outside:

- every switch is on, ``check`` passes as the runtime role nodestro_app, the API and the worker never get the owner
  role's connection, and the owner role itself is refused as a runtime role (``storage.role_unsafe``);
- ``GET /api/metrics`` answers only the operator's bearer token;
- logins through Dex go through Axentra (identity backend ``axentra``), and both identity sides agree;
- tenant secrets are stored in the ``axs1`` format;
- an uploaded input file lands in Axentra's storage, not on the data volume, and reads back unchanged;
- ``backup`` succeeds before the first upload, while Axentra's storage directory does not exist yet;
- a failed run reaches the members' in-app inbox (``/api/notifications``), and only theirs;
- the audit and usage mirrors and the run usage settlement leave nothing for ``axentra reconcile`` to write.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import time
from typing import Any

import httpx
import pytest
from test_acceptance import _finished, _flow, _start, _use_the_stub, _workflow

from conftest import ALL_SWITCHES, ORIGIN, SECRETS, Browser, Tenants, compose, new_tenant, operator, psql, wait_for

pytestmark = pytest.mark.skipif(
    not ALL_SWITCHES, reason="NODESTRO_E2E_ALL_SWITCHES=1 is not set (compose/all-switches.yaml not layered)"
)


def _owner_command(*args: str, env: dict[str, str] | None = None) -> Any:
    """``nodestro-server ARGS`` in the migrate service (the only one with the owner role's connection)."""
    flags: list[str] = []
    for key, value in (env or {}).items():
        flags += ["-e", f"{key}={value}"]
    return compose("run", "--rm", "--no-deps", "-T", *flags, "migrate", *args, check=False)


def _json_output(stdout: str) -> dict[str, Any]:
    """The JSON object a command printed last (log lines may come before it)."""
    start = stdout.index("{")
    return dict(json.loads(stdout[start:]))


# ---- switches and database roles ---------------------------------------------------------------------------------


def test_every_switch_is_on(stack: None) -> None:
    status = operator("axentra", "status").stdout
    for line in (
        "axentra: on",
        "secrets format: axs1",
        "audit mirror: on",
        "usage mirror: on",
        "run usage mirror: on",
        "notifications (inbox): on",
        "identity backend: axentra",
        "metrics endpoint: on",
        "files backend: axentra",
        "keyring: k1 (active)",
        "axentra schema: current",
    ):
        assert line in status, status


def test_check_passes_as_the_runtime_role_and_only_migrate_has_the_owner(stack: None) -> None:
    assert operator("check").stdout.strip().endswith("ready")
    config = json.loads(compose("config", "--format", "json").stdout)
    for service in ("api", "worker"):
        definition = config["services"][service]
        assert not any("MIGRATION" in key for key in definition["environment"]), definition["environment"]
        assert "database_migration_url" not in [item["source"] for item in definition["secrets"]]
        assert "NODESTRO_AXENTRA_ALLOW_SUPERUSER" not in definition["environment"]
    # Connected to the server's database right now: the runtime role only (migrate has exited).
    users = set(psql("SELECT DISTINCT usename FROM pg_stat_activity WHERE datname = 'nodestro'").split())
    assert "nodestro_app" in users and "nodestro_owner" not in users, users
    roles = _owner_command("db", "roles")
    assert roles.returncode == 0, roles.stdout + roles.stderr
    runtime = _json_output(roles.stdout)["runtime"]
    assert runtime["restricted"] is True, runtime
    # The owner role as the runtime role: refused (it owns the tables, so row-level security would not apply).
    refused = _owner_command("check", env={"NODESTRO_DATABASE_URL_FILE": "/run/secrets/database_migration_url"})
    assert refused.returncode != 0, refused.stdout
    assert "role_unsafe" in refused.stderr, refused.stderr


# ---- metrics -----------------------------------------------------------------------------------------------------


def test_metrics_answer_only_the_operators_token(stack: None) -> None:
    token = (SECRETS / "metrics_token").read_text().strip()
    url = f"{ORIGIN}/api/metrics"
    for headers in ({}, {"Authorization": "Bearer " + secrets.token_hex(32)}, {"Authorization": token}):
        refused = httpx.get(url, headers=headers, timeout=30)
        assert refused.status_code == 401, (headers.keys(), refused.status_code, refused.text)
        assert "nodestro_" not in refused.text
        assert refused.headers.get("www-authenticate", "").startswith("Bearer")
    answer = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith("text/plain")
    assert answer.headers.get("cache-control") == "no-store"
    for name in ("nodestro_axentra_switch", "nodestro_schema_version", "nodestro_workers_active"):
        assert name in answer.text, answer.text[:2000]
    assert token not in answer.text


# ---- identity ----------------------------------------------------------------------------------------------------


def test_logins_go_through_axentra_and_both_identity_sides_agree(tenants: Tenants) -> None:
    me = tenants.alice.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["tenant_id"] == tenants.acme, me.text
    assert me.json()["role"] == "owner" and me.json()["permissions"], me.json()  # decided by Axentra's roles
    linked = psql(
        "SELECT count(*) FROM nodestro_axentra_ids l JOIN axentra_users u ON u.id = l.axentra_id "
        "WHERE l.kind = 'user' AND lower(u.email) = 'alice@example.com'"
    ).strip()
    assert linked == "1", linked
    sessions = psql("SELECT count(*) FROM axentra_sessions").strip()
    assert int(sessions) >= 2, sessions  # alice's and bob's sessions live in Axentra too
    compared = operator("axentra", "reconcile-identity", check=False)
    assert compared.returncode == 0, compared.stdout + compared.stderr
    assert _json_output(compared.stdout)["ok"] is True


# ---- secrets -----------------------------------------------------------------------------------------------------


def test_tenant_secrets_are_written_in_the_axs1_format(tenants: Tenants) -> None:
    _use_the_stub(tenants.alice, key="sk-axs1-" + secrets.token_hex(8))
    status = operator("axentra", "status").stdout
    stored = next(line for line in status.splitlines() if line.startswith("stored secrets:"))
    assert "axs1" in stored and "NOT READABLE" not in status, status
    dry = operator("secrets", "reencrypt", "--dry-run")
    report = _json_output(dry.stdout)
    assert report["failed"] == [] or report["failed"] == 0, report


# ---- input files -------------------------------------------------------------------------------------------------


def test_an_uploaded_input_file_lands_in_axentras_storage(tenants: Tenants) -> None:
    alice, bob = tenants.alice, tenants.bob
    marker = "axentra-upload-" + secrets.token_hex(12)
    content = f"name,value\n{marker},1\n".encode()
    answer = alice.post("/api/inputs", files=[("files", ("upload.csv", content, "text/csv"))])
    assert answer.status_code == 201, answer.text
    results = answer.json()
    item = results[0] if isinstance(results, list) else results["files"][0]
    assert item.get("problem") is None and item.get("file"), results
    file_id = item["file"]["id"]
    back = alice.get(f"/api/inputs/{file_id}/content")
    assert back.status_code == 200 and back.content == content, back.text[:300]
    assert bob.get(f"/api/inputs/{file_id}/content").status_code == 404  # another tenant
    # The bytes are in Axentra's storage directory, not in the tenant's files on the data volume.
    where = compose(
        "exec", "-T", "api", "sh", "-c", f"grep -rl -- {marker} /var/lib/nodestro || true", check=False
    ).stdout.split()
    assert where and all(path.startswith("/var/lib/nodestro/axentra-storage/") for path in where), where
    digest = hashlib.sha256(content).hexdigest()
    stored = psql(f"SELECT count(*) FROM axentra_files WHERE sha256 = '{digest}'").strip()
    assert stored == "1", stored
    verify = operator("files", "verify", check=False)
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert _json_output(verify.stdout)["ok"] is True, verify.stdout


def test_a_backup_before_the_first_upload(stack: None) -> None:
    # A storage directory no file was written to yet, as on a new installation: Axentra's own configuration with
    # another local_path, mounted next to the real one.
    with tempfile.TemporaryDirectory() as directory:
        Path(directory).chmod(0o777)  # the image's user (10001) writes the dump
        config = Path(directory) / "fresh.toml"
        config.write_text('[storage]\nbackend = "local"\nlocal_path = "/var/lib/nodestro/axentra-storage-new"\n')
        config.chmod(0o644)
        flags = ["-v", f"{directory}:/backups", "-e", "NODESTRO_AXENTRA_CONFIG=/backups/fresh.toml"]
        result = compose("run", "--rm", "--no-deps", "-T", *flags, "migrate", "backup", "/backups", check=False)
        assert result.returncode == 0, result.stdout + result.stderr


# ---- notifications -----------------------------------------------------------------------------------------------


def _inbox(browser: Browser) -> dict[str, Any]:
    answer = browser.get("/api/notifications")
    assert answer.status_code == 200, answer.text
    return dict(answer.json())


def test_a_failed_run_reaches_the_members_inbox_only(tenants: Tenants) -> None:
    assert Browser(None).get("/api/notifications").status_code == 401
    _, bob = new_tenant("bob", "initech")
    assert _inbox(bob)["items"] == []
    # A provider endpoint the operator allowed (the stub's origin) that answers 404: the run fails.
    answer = bob.put(
        "/api/settings",
        json={
            "providers": {
                "compatible": {
                    "base_url": "http://localhost:9100/broken/v1",
                    "api_key": "x",
                    "capabilities": {"tools": "supported", "streaming": "supported"},
                }
            }
        },
    )
    assert answer.status_code == 200, answer.text
    run_id = _start(bob, _workflow(bob, _flow("Fails", "ECHO")))
    run = _finished(bob, run_id)
    assert run["status"] == "failed", run
    # The worker's platform duties send it (every 30 s, while it holds the scheduler lock).
    inbox = wait_for(
        lambda: (page := _inbox(bob))["items"] and page, timeout=120, every=2, what="the run_failed notification"
    )
    kinds = [item["kind"] for item in inbox["items"]]
    assert any("run_failed" in kind for kind in kinds), inbox
    assert inbox["unread"] >= 1, inbox
    assert all("initech" not in json.dumps(item) for item in _inbox(tenants.alice)["items"])  # another tenant
    marked = bob.post("/api/notifications/read", json={"ids": []})
    assert marked.status_code == 200 and marked.json()["marked"] >= 1, marked.text
    assert _inbox(bob)["unread"] == 0
    time.sleep(35)  # one more round of the platform duties: no second notification for the same run
    assert len(_inbox(bob)["items"]) == len(inbox["items"])


# ---- audit and usage mirrors ---------------------------------------------------------------------------------------


def test_the_mirrors_leave_nothing_to_reconcile(tenants: Tenants) -> None:
    alice = tenants.alice
    _use_the_stub(alice)
    run = _finished(alice, _start(alice, _workflow(alice, _flow("Metered", "ECHO")), "count me"))
    assert run["status"] == "succeeded", run
    usage = int(psql("SELECT count(*) FROM axentra_usage_events").strip() or 0)
    assert usage >= 1, usage

    def settled() -> dict[str, Any] | None:
        report = _json_output(operator("axentra", "reconcile", "--dry-run").stdout)
        missing = report["audit_missing"] + report["usage_missing"] + report["runs_missing"] + report["runs_changed"]
        return report if missing == 0 else None

    report = wait_for(settled, timeout=150, every=10, what="the run usage settlement")
    assert report["failed"] == 0, report
