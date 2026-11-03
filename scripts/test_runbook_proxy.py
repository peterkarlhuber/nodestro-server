#!/usr/bin/env python3
"""Tests of the nginx example in docs/RUNBOOK.md ("TLS reverse proxy"): setup links (``?setup=``) and sign-in codes
(``?code=``, ``&state=``) must reach neither the proxy's access log nor its error log (OPS2-02, D-02).

The static tests read the example. With Docker (``NODESTRO_PROXY_PROBE=1``, set in CI) nginx runs the example with
the API unreachable, the worst case for the error log, and both logs are searched for the probe values.
Run: python3 -I scripts/test_runbook_proxy.py"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid

RUNBOOK = Path(__file__).resolve().parent.parent / "docs" / "RUNBOOK.md"
# nginx 1.28 (stable), pinned by digest like every other image of this repository.
# NODESTRO_PROXY_PROBE_IMAGE overrides it (for example a registry mirror with the same digest).
NGINX_IMAGE = os.environ.get(
    "NODESTRO_PROXY_PROBE_IMAGE",
    "nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236",
)
# Paths whose query strings carry login secrets (nodestro_api.identity._AUTH_QUERY and the MCP sign-in callback).
SECRET_PATHS = ("/api/auth/login", "/api/auth/callback", "/api/mcp/oauth/callback")
# Variables that contain the query string (the predefined "combined" format uses $request).
QUERY_VARIABLES = ("$request", "$request_uri", "$args", "$query_string", "$is_args", "$http_referer", "$arg_")


def example() -> str:
    text = RUNBOOK.read_text(encoding="utf-8")
    section = text.split("\n## TLS reverse proxy\n", 1)[1].split("\n## ", 1)[0]
    blocks = re.findall(r"```nginx\n(.*?)```", section, re.S)
    if len(blocks) != 1:
        raise AssertionError(f"expected one nginx block in 'TLS reverse proxy', found {len(blocks)}")
    return blocks[0]


def strip_comments(config: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in config.splitlines())


def locations(config: str) -> dict[str, str]:
    """Location pattern -> body (the example has no nested blocks inside a location)."""
    return {m.group(1).strip(): m.group(2) for m in re.finditer(r"location\s+([^{]+)\{([^}]*)\}", config)}


def location_for(path: str, config: str) -> str:
    """The body nginx would pick for ``path`` (exact match first, then the longest prefix; no regex locations)."""
    found = locations(config)
    if f"= {path}" in found:
        return found[f"= {path}"]
    prefixes = [p for p in found if not p.startswith(("=", "~")) and path.startswith(p)]
    return found[max(prefixes, key=len)]


class StaticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = strip_comments(example())

    def test_log_formats_contain_no_query_string(self) -> None:
        formats = re.findall(r"log_format\s+(\S+)\s+((?:'[^']*'\s*)+);", self.config)
        self.assertTrue(formats, "the example defines its own log_format")
        for name, body in formats:
            for variable in QUERY_VARIABLES:
                self.assertNotRegex(
                    body,
                    re.escape(variable) + r"(?![\w])" if variable != "$arg_" else r"\$arg_",
                    f"log_format {name} logs {variable}",
                )

    def test_maps_strip_the_query_string(self) -> None:
        for source in ("$request_uri", "$http_referer"):
            body = re.search(r"map\s+" + re.escape(source) + r"\s+\S+\s*\{([^}]*)\}", self.config)
            self.assertIsNotNone(body, f"map for {source}")
            self.assertIn("[^?]*", body.group(1))

    def test_every_access_log_names_the_format(self) -> None:
        formats = set(re.findall(r"log_format\s+(\S+)", self.config))
        access_logs = re.findall(r"access_log\s+([^;]+);", self.config)
        self.assertTrue(access_logs, "the example sets its access log (else nginx uses 'combined')")
        for directive in access_logs:
            parts = directive.split()
            if parts == ["off"]:
                continue
            self.assertGreaterEqual(len(parts), 2, f"access_log {directive} uses the default 'combined' format")
            self.assertIn(parts[1], formats, f"access_log {directive}")

    def test_error_log_is_critical_only_where_secrets_arrive(self) -> None:
        for path in SECRET_PATHS:
            body = location_for(path, self.config)
            level = re.search(r"error_log\s+\S+\s+(\w+)\s*;", body)
            self.assertIsNotNone(level, f"location for {path} sets its own error_log")
            self.assertIn(level.group(1), ("crit", "alert", "emerg"), path)


@unittest.skipUnless(
    os.environ.get("NODESTRO_PROXY_PROBE") == "1" and shutil.which("docker"), "NODESTRO_PROXY_PROBE=1 and Docker"
)
class NginxProbe(unittest.TestCase):
    """nginx with the example (TLS replaced by plain http on 8443, the API on 8080 unreachable)."""

    def test_no_secret_in_access_or_error_log(self) -> None:
        config = example()
        config = re.sub(r"listen 443 ssl;", "listen 8443;", config)
        config = re.sub(r"^\s*ssl_certificate(_key)?\s.*\n", "", config, flags=re.M)
        config = config.replace("/var/log/nginx/studio.access.log", "/dev/stdout")
        config = config.replace("/var/log/nginx/studio.error.log", "/dev/stderr")
        name = f"nodestro-proxy-probe-{uuid.uuid4().hex[:8]}"
        probes = {
            "/api/auth/login?setup=SETUP-PROBE-6c1f": "SETUP-PROBE-6c1f",
            "/api/auth/callback?code=CODE-PROBE-93ab&state=STATE-PROBE-41d0": "PROBE-",
            "/api/mcp/oauth/callback?code=MCP-CODE-PROBE-7e2a&state=MCP-STATE-PROBE-0b5c": "PROBE-",
            "/assets/app.js?v=VISIBLE-PATH-PROBE": "VISIBLE-PATH-PROBE",
        }
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "default.conf"
            conf.write_text(config, encoding="utf-8")
            conf.chmod(0o644)
            subprocess.run(
                ["docker", "run", "-d", "--name", name, "-v", f"{conf}:/etc/nginx/conf.d/default.conf:ro", NGINX_IMAGE],
                check=True,
                capture_output=True,
            )
            try:
                for _ in range(50):
                    ok = subprocess.run(["docker", "exec", name, "nginx", "-t"], capture_output=True, text=True)
                    if ok.returncode == 0:
                        break
                    time.sleep(0.2)
                self.assertEqual(ok.returncode, 0, ok.stderr)
                for path in probes:
                    # A referrer with a query: the access log drops it everywhere; the error log quotes it, so it is
                    # sent only to the locations whose error log is critical-only.
                    referer = (
                        []
                        if path.startswith("/assets/")
                        else ["--header", "Referer: https://idp.example.com/authorize?state=REFERER-PROBE-55aa"]
                    )
                    subprocess.run(
                        [
                            "docker",
                            "exec",
                            name,
                            "wget",
                            "-q",
                            "-O",
                            "/dev/null",
                            *referer,
                            f"http://127.0.0.1:8443{path}",
                        ],
                        capture_output=True,
                    )
                time.sleep(0.5)
                logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
                output = logs.stdout + logs.stderr
            finally:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        lines = [line for line in output.splitlines() if "/api/" in line or "/assets/" in line]
        # Every request is logged (by path), the upstream failed (502), no query value is in any log line.
        for path in ("/api/auth/login", "/api/auth/callback", "/api/mcp/oauth/callback", "/assets/app.js"):
            self.assertTrue(any(f"GET {path} " in line and " 502 " in line for line in lines), (path, output))
        for marker in ("PROBE-", "setup=", "code=", "state="):
            self.assertNotIn(marker, output.replace("VISIBLE-PATH-PROBE", ""), output)
        # The error log still reports failures of the other locations (nginx did not go silent everywhere).
        self.assertIn("connect() failed", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
