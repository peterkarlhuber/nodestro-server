"""A real upgrade of the PostgreSQL stack: the previous release (``tests/upgrade-from.json``: its compose file and its
image) with data is updated to the current compose file and image the way docs/RUNBOOK.md says ("Upgrade"), rolled
back ("Releases and rollback"), upgraded again, and a backup written by the previous release is restored by the
current one. The acceptance tests start every stack from scratch; this test catches migrations that fail or hang on
a database written by an older release (OPS2-01: ``migrate --backup-dir`` deadlocked on databases from before
migration checksums).

Built and run by .github/workflows/upgrade.yml; by hand, with a checkout of the previous server commit that only this
test uses (its ``compose/.secrets`` is replaced):

    git worktree add ../server-upgrade-from "$(jq -r '.["nodestro-server"]' tests/upgrade-from.json)"
    ../server-upgrade-from/scripts/build-image.sh nodestro-server:upgrade-from
    scripts/build-image.sh nodestro-server:dev
    NODESTRO_UPGRADE_FROM=../server-upgrade-from NODESTRO_UPGRADE_FROM_IMAGE=nodestro-server:upgrade-from \\
        NODESTRO_IMAGE=nodestro-server:dev python -m pytest tests/e2e/test_upgrade.py -v -p no:cacheprovider

It starts and removes the stack itself (``docker compose down -v`` at the end), so nothing else may run on the
development stack's ports meanwhile. Behind a TLS-inspecting proxy, set NODESTRO_EXTRA_CA_FILE as for scripts/e2e.sh.
Without NODESTRO_UPGRADE_FROM the module is skipped (scripts/e2e.sh runs one image only).
"""

from __future__ import annotations

from collections.abc import Iterator
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest

FROM_DIR = os.environ.get("NODESTRO_UPGRADE_FROM", "")
if not FROM_DIR:
    pytest.skip("NODESTRO_UPGRADE_FROM (a checkout of the previous server commit) is not set", allow_module_level=True)

from test_acceptance import _finished, _flow, _start, _use_the_stub, _workflow  # noqa: E402

from conftest import ROOT, SECRETS, Browser, accounts, compose, login, operator, wait_healthy  # noqa: E402

OLD = Path(FROM_DIR).resolve()
# The previous release's own test helpers drive its API (its login flow differs: no login cookie before the backend
# audit). Loaded under another name, next to this checkout's conftest.
_spec = importlib.util.spec_from_file_location("upgrade_from_conftest", OLD / "tests" / "e2e" / "conftest.py")
assert _spec and _spec.loader, OLD
previous = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = previous  # its dataclasses look the module up
_spec.loader.exec_module(previous)
OLD_IMAGE = os.environ.get("NODESTRO_UPGRADE_FROM_IMAGE", "nodestro-server:upgrade-from")
NEW_IMAGE = os.environ.get("NODESTRO_IMAGE", "nodestro-server:dev")
EXTRA_CA = os.environ.get("NODESTRO_EXTRA_CA_FILE", "")
#: Seconds for db-roles, ``migrate --backup-dir`` and the API and worker to come up after a switch. The migrations
#: of a small database take seconds; the OPS2-01 deadlock hung until PostgreSQL's idle-in-transaction timeout.
UPGRADE_SECONDS = int(os.environ.get("NODESTRO_UPGRADE_SECONDS", "240"))
BACKUPS = "/var/lib/nodestro/backups"  # compose/compose.yaml: migrate --backup-dir
TENANT = "acme-upgrade"
# The restore of scripts/restore.sh (scripts/restore_dump.py), for a dump on the data volume: as the owner role, in
# one transaction, without extensions and without the newer release's tables.
RESTORE = (ROOT / "scripts" / "restore_dump.py").read_text(encoding="utf-8")


def _use(checkout: Path, image: str) -> None:
    """Point the following ``docker compose`` calls at a release: its compose file (same project name, so the same
    volumes) and its image."""
    files = [checkout / "compose" / "compose.yaml"]
    if EXTRA_CA:
        files.append(checkout / "compose" / "extra-ca.yaml")
    os.environ["COMPOSE_FILE"] = ":".join(str(file) for file in files)
    os.environ["NODESTRO_IMAGE"] = image


def _logs() -> str:
    return compose(
        "logs", "--no-color", "--tail=60", "db-roles", "migrate", "api", "worker", check=False, timeout=120
    ).stdout


def _switch_to_new_release() -> None:
    """RUNBOOK "Upgrade" step 3 with the development stack: the API and the worker are stopped; the new compose file
    and image start db-roles and ``migrate --backup-dir`` (compose.yaml), then the API and the worker. Bounded: a
    migration that hangs fails here instead of holding the job until its timeout."""
    _use(ROOT, NEW_IMAGE)
    compose("up", "-d", "--wait", "--wait-timeout", "900", "postgres", "dex", "sandbox", "model-stub", timeout=1800)
    command = ("up", "-d", "--wait", "--wait-timeout", str(UPGRADE_SECONDS), "--remove-orphans", "api", "worker")
    try:
        result = compose(*command, check=False, timeout=UPGRADE_SECONDS + 60)
    except subprocess.TimeoutExpired:
        pytest.fail(f"the upgrade did not finish within {UPGRADE_SECONDS + 60} s (hung migration?)\n{_logs()}")
    assert result.returncode == 0, (
        f"the upgrade failed or did not finish within {UPGRADE_SECONDS} s (the OPS2-01 deadlock looked like this: "
        f"migrate hung, then failed with an idle-in-transaction timeout)\n{result.stdout}\n{result.stderr}\n{_logs()}"
    )


def _pre_migration_dumps() -> list[str]:
    """The backups that the new release's ``migrate --backup-dir`` wrote, oldest first (the names carry the time)."""
    listing = compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "ls", "migrate", "-1", BACKUPS).stdout
    dumps = [name for name in listing.split() if name.startswith("pre-migration-") and name.endswith(".dump")]
    return sorted(dumps, key=lambda name: name.rsplit("-", 1)[-1])


def _alice() -> Browser:
    """alice in the tenant, logged in at the current release."""
    return login(accounts()["alice"], tenant=TENANT)


def _alice_at_the_previous_release() -> Any:
    return previous.login(previous.accounts()["alice"], tenant=TENANT)


def _names(browser: Any) -> set[str]:
    answer = browser.get("/api/workflows")
    assert answer.status_code == 200, answer.text
    body: Any = answer.json()
    items = body if isinstance(body, list) else body.get("items", [])
    return {str(item["name"]) for item in items}


def _runs(browser: Any, workflow_id: str) -> None:
    run = _finished(browser, _start(browser, workflow_id))
    assert run["status"] == "succeeded", run


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[None]:
    """The development stack of the previous release with fresh secrets, removed with its volumes afterwards. The
    current checkout's compose/.secrets is set aside and put back."""
    pinned = json.loads((ROOT / "tests" / "upgrade-from.json").read_text())
    head = subprocess.run(["git", "-C", str(OLD), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    assert head.stdout.strip() == pinned["nodestro-server"], f"{OLD} is not at tests/upgrade-from.json's commit"
    old_studio = json.loads((OLD / "studio.json").read_text())["nodestro-studio"]
    assert old_studio == pinned["nodestro-studio"], "tests/upgrade-from.json names another studio commit"
    labels = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{json .Config.Labels}}", OLD_IMAGE],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(labels.stdout).get("dev.nodestro.studio-commit") == old_studio, f"{OLD_IMAGE} is another build"
    assert OLD_IMAGE != NEW_IMAGE

    for checkout, image in ((ROOT, NEW_IMAGE), (OLD, OLD_IMAGE)):
        _use(checkout, image)
        compose("down", "-v", "--remove-orphans", check=False, timeout=300)
    set_aside = tmp_path / "secrets-before-the-test"
    if SECRETS.exists():
        shutil.move(SECRETS, set_aside)
    shutil.rmtree(OLD / "compose" / ".secrets", ignore_errors=True)
    subprocess.run(["python3", str(OLD / "scripts" / "dev-secrets.py")], check=True)
    try:
        # The operator keeps the secrets when updating the checkout; the new dev-secrets.py adds what is missing
        # (the owner and runtime roles' passwords) and moves database_url to the runtime role.
        shutil.copytree(OLD / "compose" / ".secrets", SECRETS)
        subprocess.run(["python3", str(ROOT / "scripts" / "dev-secrets.py")], check=True)
        _use(OLD, OLD_IMAGE)
        yield
    finally:
        print(_logs())  # shown for a failed test only
        for checkout, image in ((ROOT, NEW_IMAGE), (OLD, OLD_IMAGE)):
            _use(checkout, image)
            compose("down", "-v", "--remove-orphans", check=False, timeout=300)
        shutil.rmtree(SECRETS, ignore_errors=True)
        if set_aside.exists():
            shutil.move(set_aside, SECRETS)


def test_upgrade_rollback_and_reupgrade_keep_the_data(stack: None, tmp_path: Path) -> None:
    # The previous release with data: a tenant, its first owner, a provider key (encrypted with the secret key), a
    # workflow and a finished run.
    compose("up", "-d", "--wait", "--wait-timeout", "900", timeout=1800)
    operator("create-tenant", TENANT, "Acme Upgrade")
    link = operator("setup-link", TENANT).stdout.strip().splitlines()[-1]
    alice = previous.login(previous.accounts()["alice"], setup=link.split("setup=", 1)[1])
    _use_the_stub(alice)
    old_workflow = _workflow(alice, _flow("Written by the old release", "ALPHA"))
    _runs(alice, old_workflow)

    # RUNBOOK "Upgrade" step 2: a backup with the previous release's image.
    backups = tmp_path / "backups"
    backups.mkdir()
    backups.chmod(0o777)  # the image's user (10001) writes the dump
    printed = compose("run", "--rm", "--no-deps", "-T", "-v", f"{backups}:/backups", "migrate", "backup", "/backups")
    old_backup = backups / next(Path(line).name for line in printed.stdout.split() if line.endswith(".dump"))
    assert old_backup.read_bytes().startswith(b"PGDMP")
    _workflow(alice, _flow("Not in the old backup", "ALPHA"))
    before = {"Written by the old release", "Not in the old backup"}

    # Step 3: stop the API and the worker, then the new release (migrate --backup-dir first).
    compose("stop", "api", "worker")
    _switch_to_new_release()
    assert len(_pre_migration_dumps()) == 1, "migrate --backup-dir wrote no backup before migrating"
    alice = _alice()
    assert _names(alice) == before
    _runs(alice, old_workflow)  # the stored provider key still decrypts; the new worker runs old workflows
    _workflow(alice, _flow("Written by the new release", "ALPHA"))

    # RUNBOOK "Releases and rollback": stop the API and the worker, restore the backup that the new release's
    # migrate wrote, start the previous release's migrate, API and worker.
    compose("stop", "api", "worker")
    dump = _pre_migration_dumps()[-1]
    compose(
        "run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "migrate", "-I", "-c", RESTORE, f"{BACKUPS}/{dump}"
    )
    _use(OLD, OLD_IMAGE)
    compose("up", "-d", "--wait", "--wait-timeout", "900", "--remove-orphans", "api", "worker", timeout=1800)
    alice = _alice_at_the_previous_release()
    assert _names(alice) == before, "the rollback lost data or kept the new release's writes"
    _runs(alice, old_workflow)

    # Upgrade again after the rollback (the restore dropped the newer release's tables; migrate creates them again).
    compose("stop", "api", "worker")
    _switch_to_new_release()
    assert len(_pre_migration_dumps()) == 2
    alice = _alice()
    assert _names(alice) == before
    _workflow(alice, _flow("Written after the second upgrade", "ALPHA"))

    # A backup written by the previous release, restored by the current one (scripts/restore.sh: pg_restore, then
    # migrate --backup-dir on the old schema again).
    restored = subprocess.run(
        ["bash", str(ROOT / "scripts" / "restore.sh"), str(old_backup)],
        capture_output=True,
        text=True,
        check=False,
        timeout=UPGRADE_SECONDS + 300,
    )
    assert restored.returncode == 0, restored.stdout + restored.stderr + _logs()
    wait_healthy("api")
    wait_healthy("worker")
    alice = _alice()
    assert _names(alice) == {"Written by the old release"}
    _runs(alice, old_workflow)
    _workflow(alice, _flow("Written after the restore", "ALPHA"))
    assert _names(alice) == {"Written by the old release", "Written after the restore"}
