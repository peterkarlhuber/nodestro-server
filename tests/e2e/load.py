"""A load test of a running development stack (compose/compose.yaml): many tenants start runs at the same time.

    NODESTRO_IMAGE=nodestro-server:dev KEEP_STACK=1 scripts/e2e.sh -k test_the_configured_server_is_ready
    python3 tests/e2e/load.py --tenants 4 --runs 25 --concurrency 16 --workers 2 [--json report.json]

It drives the stack like the acceptance tests do (conftest.py: logins through Dex, operator commands), with the
OpenAI-compatible model stub, so it measures the server (API, workers, PostgreSQL), not a model provider:

1. ``--workers`` worker processes (``docker compose up --scale worker=N``);
2. ``--tenants`` new tenants owned by alice, each with the stub as its model endpoint and one workflow (one agent);
3. ``--runs`` runs per tenant, started from ``--concurrency`` threads; each is followed until it is finished;
4. while they run and afterwards: the latency of ``GET /api/runs`` and ``GET /api/usage`` per tenant.

The report: runs per second, start latency, time from start to finished (percentiles), list and usage latency, and
how many runs did not succeed. The numbers are only as good as the machine: a development machine shares its CPUs
with the stack, so its figures are not those of target hardware (see docs/RUNBOOK.md, "Load test").
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import threading
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import Browser, accounts, compose, login, new_tenant, wait_healthy

STUB = "http://localhost:9100/v1"


def percentiles(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)

    def at(share: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 3)

    return {"count": len(values), "p50": at(0.5), "p90": at(0.9), "p99": at(0.99), "max": round(ordered[-1], 3),
            "mean": round(statistics.fmean(values), 3)}  # fmt: skip


def timed(call: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = call()
    return time.perf_counter() - started, result


def prepare(tenants: int) -> list[tuple[str, Browser, str]]:
    """New tenants with the stub as their model endpoint and one workflow each: (tenant, session, workflow id)."""
    login(accounts()["alice"])  # alice must have logged in once, so that set-role knows her
    prepared = []
    for _ in range(tenants):
        tenant, owner = new_tenant("alice", "load")
        supported = {name: "supported" for name in ("tools", "streaming")}
        saved = owner.put(
            "/api/settings",
            json={"providers": {"compatible": {"base_url": STUB, "api_key": "stub-key", "capabilities": supported}}},
        )
        assert saved.status_code == 200, saved.text
        flow = {
            "name": "Load test",
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "a", "type": "agent", "label": "A",
                 "agent": {"name": "A", "system_prompt": "load", "model": "compatible:stub-model", "effort": None}},
                {"id": "out", "type": "output"},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "a"}, {"id": "e2", "source": "a", "target": "out"}],
        }  # fmt: skip
        created = owner.post("/api/workflows", json=flow)
        assert created.status_code == 201, created.text
        prepared.append((tenant, owner, str(created.json()["id"])))
    return prepared


def one_run(owner: Browser, workflow: str, number: int, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    answer = owner.post(f"/api/workflows/{workflow}/runs", json={"input": f"load {number}"})
    accepted = time.perf_counter() - started
    if answer.status_code != 201:
        return {"status": f"refused {answer.status_code}", "start": accepted}
    run_id = answer.json()["id"]
    deadline = started + timeout
    status = "timeout"
    while time.perf_counter() < deadline:
        found = owner.get(f"/api/runs/{run_id}")
        if found.status_code == 200 and found.json()["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
            status = found.json()["status"]
            break
        time.sleep(0.2)
    return {"status": status, "start": accepted, "total": time.perf_counter() - started}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenants", type=int, default=4)
    parser.add_argument("--runs", type=int, default=25, help="runs per tenant")
    parser.add_argument("--concurrency", type=int, default=16, help="runs started and followed at the same time")
    parser.add_argument("--workers", type=int, default=2, help="worker processes (docker compose --scale)")
    parser.add_argument("--timeout", type=float, default=600, help="seconds a run may take")
    parser.add_argument("--json", type=Path, help="also write the report here")
    args = parser.parse_args(argv)
    os.environ.setdefault("COMPOSE_FILE", str(Path(__file__).resolve().parents[2] / "compose" / "compose.yaml"))
    for service in ("postgres", "api", "worker", "model-stub"):
        wait_healthy(service)
    compose("up", "-d", "--no-deps", "--no-recreate", "--scale", f"worker={args.workers}", "worker")
    prepared = prepare(args.tenants)

    queries: dict[str, list[float]] = {"runs": [], "usage": []}
    stop = threading.Event()

    def poll_lists() -> None:  # the views people keep open while runs happen
        while not stop.is_set():
            for _, owner, _ in prepared:
                for name, path in (("runs", "/api/runs"), ("usage", "/api/usage")):
                    seconds, answer = timed(lambda path=path, owner=owner: owner.get(path))
                    if answer.status_code == 200:
                        queries[name].append(seconds)
            time.sleep(0.5)

    poller = threading.Thread(target=poll_lists, daemon=True)
    poller.start()
    jobs = [(owner, workflow, n) for n in range(args.runs) for _, owner, workflow in prepared]
    began = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda job: one_run(*job, timeout=args.timeout), jobs))
    elapsed = time.perf_counter() - began
    stop.set()
    poller.join()
    after = {name: [timed(lambda p=path, o=owner: o.get(p))[0] for _, owner, _ in prepared]
             for name, path in (("runs_after", "/api/runs"), ("usage_after", "/api/usage"))}  # fmt: skip

    statuses: dict[str, int] = {}
    for result in results:
        statuses[result["status"]] = statuses.get(result["status"], 0) + 1
    report = {
        "machine": {"cpus": os.cpu_count(), "platform": platform.platform(), "note": "not target hardware"},
        "settings": vars(args) | {"json": str(args.json) if args.json else None},
        "runs": len(results),
        "statuses": statuses,
        "seconds": round(elapsed, 2),
        "runs_per_second": round(len(results) / elapsed, 2) if elapsed else None,
        "start_latency": percentiles([r["start"] for r in results]),
        "run_duration": percentiles([r["total"] for r in results if "total" in r]),
        "list_runs_during": percentiles(queries["runs"]),
        "usage_during": percentiles(queries["usage"]),
        "list_runs_after": percentiles(after["runs_after"]),
        "usage_after": percentiles(after["usage_after"]),
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")
    return 0 if statuses.get("succeeded", 0) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
