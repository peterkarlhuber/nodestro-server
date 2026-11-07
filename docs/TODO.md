# TODO: nodestro-server

> Open work for this repository: release blockers, known bugs, security follow-ups, technical debt and planned improvements.
> GitHub issues are the source of truth for details; this file is the entry point and summary.
>
> **Last full review:** 2026-11-07 against `master` at `9d918aa` (TODO abatement round 4).

## Summary

| Priority | Count |
|---|---|
| P0 Critical | 0 |
| P1 High | 0 |
| P2 Medium | 7 |
| P3 Low | 3 |
| P4 Optional | 1 |

**Release blockers:** None for this repository; no entry here blocks the next planned preview (the desktop
candidate, nodestro-desktop DSK-001). No server release or production deployment is approved; a new server
candidate may be prepared, but publishing needs an explicit owner decision (SRV-001, not a release blocker).

The server image, compose stack, acceptance tests and runbook are in good shape for a supervised pilot on Linux
amd64 (CI also runs the acceptance tests on arm64). For production use, the gaps are operational: observability,
reproducible builds, load tests on target hardware, a staging drill and an external security review.

## Priorities and statuses

- **P0 Critical**: data loss, security exposure, or broken core function; blocks any release.
- **P1 High**: blocks a planned release or a promised capability, or a significant risk.
- **P2 Medium**: real defect or gap with a workaround; schedule soon.
- **P3 Low**: minor defect, polish, or small debt.
- **P4 Optional**: improvement idea; not a defect.

Statuses: `Open`, `In progress` (PR linked), `Blocked` (names the blocker), `Needs decision` (owner decision pending),
`Needs external review`, `Accepted risk` (deliberately not fixed; reason stated).

## Release blockers and critical items

### SRV-001 · Rebuild the server release candidate and decide on publishing

- **Priority:** P2 Medium · **Status:** Needs decision · **Refs:** RUNBOOK "Releases and rollback", project release notes 2026-10-31
- **What:** The only server candidate (`v0.2.0-preview.1`, built 2026-10-31 from studio `78710ce`) predates the
  backend audit, Bedrock and Live Run Chat work and is outdated. Tags, GHCR pushes and releases are not approved.
- **Next step:** From the current pins (`studio.json`; studio `58bb17d` since 2026-11-06), run `release.yml` again (it now
  also writes the vulnerability reports), record a Go/No-Go, and ask the owner whether to publish. Do not run `publish.yml` without that approval.

## Security

### SRV-004 · External security review before any production use

- **Priority:** P2 Medium · **Status:** Needs external review · **Refs:** backend audit 2026-11-01 section 16
- **What:** The backend audit was internal. No external penetration test of a server deployment (OIDC login, tenant
  isolation, sandbox daemon, Bedrock role assumption) has been done. MCP is accepted only for a read-only pilot, and
  tool approvals (S-2) stay off outside an isolated pilot pending their own independent review (nodestro-runtime
  RT-001). The Axentra switches wait for an external sign-off (nodestro-runtime RT-030, SRV-019), and the portable
  export (nodestro-api #85, nodestro-studio #121, with the api #87 hardening) needs an independent review owned in
  nodestro-api; server export jobs stay off by default (`NODESTRO_SERVER_EXPORT_JOBS`, API-048).
- **Next step:** Commission an external test of a deployment built from a current candidate; keep MCP write tools,
  `NODESTRO_TOOL_APPROVALS` and `NODESTRO_SERVER_EXPORT_JOBS` off until the respective reviews pass.

## Bugs and reliability

None known.

## Architecture and modularity

The image definition here is shared with nodestro-local-docker by design; see its `docs/ARCHITECTURE.md`.

### SRV-019 · Axentra platform services on a staging server

- **Priority:** P2 Medium · **Status:** Open · **Refs:** RUNBOOK "Axentra platform services" and "Database roles",
  nodestro-runtime `docs/AXENTRA.md` and RT-030
- **What:** Every Axentra switch of the server (keyring secrets, tenant links, audit, usage and run-usage mirrors,
  the inbox, identity `mirror`/`axentra`, input files) is merged and off by default; none is approved for
  production. They are tested against PostgreSQL in the component repositories and with every switch on in the
  development stack (`NODESTRO_E2E_ALL_SWITCHES=1 scripts/e2e.sh`, CI too), not yet on a staging server with a
  copy of real data and a restore drill.
- **Next step:** On a staging copy of production data: move it to the separate roles (RUNBOOK), `migrate
  --backup-dir`, `db roles`, `axentra backfill-identity --dry-run` and then without it, `axentra
  reconcile-identity` (`"ok": true`), `secrets reencrypt`, `axentra reconcile`, `files migrate` and `files verify`
  against a real S3 bucket; then restore the backup as the owner and compare. Production activation is decided per
  switch afterwards, not before the independent review (RT-030).
- **Depends on:** nodestro-runtime RT-030 (independent security review)

## Performance

### SRV-020 · Semantic knowledge search at server scale

- **Priority:** P3 Low · **Status:** Open · **Refs:** nodestro-runtime `docs/local-models.md`, migration `0010`
- **What:** pgvector ranks the vectors with exact cosine similarity (no HNSW/IVFFlat index), and the embedding model
  runs on an operator's Ollama endpoint. Neither was measured on server hardware with many tenants and large
  knowledge bases. Since 2026-11-06 an acceptance test builds a tenant's index through the model stub's Ollama API
  (`/api/embed`) and searches it with pgvector (`test_a_semantic_index_is_built_through_the_operators_embedding_endpoint`);
  it checks function and tenant isolation, not speed.
- **Next step:** Measure search latency and reindex throughput on target hardware with large knowledge bases (with
  SRV-013); decide on an approximate index.

## Features and enhancements

### SRV-007 · Monitoring section in the runbook

- **Priority:** P2 Medium · **Status:** Blocked (on nodestro-api observability, backend audit D-10) · **Refs:** backend audit D-10
- **What:** The runbook covers health checks, readiness (`/api/ready`), request ids, JSON logs and the metrics
  endpoint ("Health checks", "Metrics and status"). Since 2026-11-07 the development stack and the production
  example check the API with `/api/ready` and log JSON, and `test_readiness_request_ids_and_json_logs` checks all
  three. Left: workers have no liveness signal besides `nodestro-server check`, and there is no tracing.
- **Next step:** When the API adds a worker liveness signal (and optional tracing), document it and use it in the
  worker's health check.
- **Depends on:** nodestro-api API-011 (observability, D-10)

## Tests and quality assurance

None open; see SRV-010 and SRV-011 for platform coverage.

## Platform coverage

### SRV-010 · Browsers against the server image

- **Priority:** P2 Medium · **Status:** Open · **Refs:** RUNBOOK "System requirements (tested)"
- **What:** The acceptance tests use HTTP clients only. No browser (Chromium, Firefox, Safari) has been run against
  a server with OIDC login, `__Host-` cookies and the TLS proxy.
- **Next step:** Run the studio browser suites against the compose stack behind a TLS proxy (at least Chromium).

### SRV-011 · Untested infrastructure

- **Priority:** P2 Medium · **Status:** Open · **Refs:** RUNBOOK "System requirements (tested)"
- **What:** Untested: identity providers other than Dex (Keycloak, Entra ID, Okta), a remote sandbox Docker host
  over mutual TLS, Podman, Kubernetes, Docker Desktop, PostgreSQL major versions other than 17, and Amazon Bedrock
  tenant roles against real AWS STS (live calls not yet approved).
  PostgreSQL 16 and 18 were tried once on 2026-11-07 (`NODESTRO_POSTGRES_IMAGE`, RUNBOOK): 16 runs everything but
  a restore (the image's `pg_dump` 17 writes a setting 16 rejects), 18 does not start with the stack's data mount.
- **Next step:** Test at least one production identity provider and a remote sandbox host before a pilot; record
  results in the runbook table. Decide whether 16 or 18 must be supported (restore with a matching `pg_dump`, the
  18 data mount).

### SRV-013 · PostgreSQL load test on target hardware

- **Priority:** P3 Low · **Status:** Open · **Refs:** backend audit C-14, C-05; nodestro-runtime RT-008, RT-020
- **What:** Store throughput was measured only locally (still about 12 % below the pre-audit figure), and
  `/api/usage` grows linearly with the number of runs. `tests/e2e/load.py` (RUNBOOK "Load test") drives the
  development stack with many tenants, concurrent runs and several workers; its first run was on a shared 4-CPU
  development machine (2026-11-06: 200 runs, 4 tenants, 3 workers, all succeeded, 12.9 runs/s), not on server
  hardware.
- **Next step:** Run `tests/e2e/load.py` against a pilot setup on target hardware with realistic tenants, runs and
  workers; feed results back to nodestro-runtime/nodestro-api.

## Documentation

None known beyond SRV-007.

## Technical debt

### SRV-014 · Reproducible image builds

- **Priority:** P3 Low · **Status:** Open · **Refs:** #28, backend audit D-05; same decision as nodestro-runtime RT-023
- **What:** Third-party Python dependencies are resolved at build time inside version ranges; two builds of the same
  `studio.json` can differ.
- **Next step:** Hashed constraints file next to `studio.json`, installed with `--require-hashes` (see #28).

## Later optimizations

### SRV-017 · Production deployment example

- **Priority:** P4 Optional · **Status:** Needs decision · **Refs:** backend audit D-16 recommendation, RUNBOOK "Production example"
- **What:** `compose/production.example.yaml` (RUNBOOK "Production example": external PostgreSQL, OIDC, remote
  sandbox host over mutual TLS, Caddy, limits, read-only containers) exists since 2026-11-06 as an example; CI checks
  only that its configuration is valid. No deployment form is supported or tested yet.
- **Next step:** Owner decision on the supported deployment form (compose, Helm, both); then test it on real hosts.

## Accepted risks

### SRV-018 · Unsigned preview images without provenance

- **Priority:** P2 Medium · **Status:** Accepted risk · **Refs:** backend audit D-09
- **What:** Images are not signed and carry no provenance attestation; the manifest and labels say `unsigned`.
  Accepted because nothing is released and preview versions are not meant for production data.
- **Next step:** Close (signing key, attestation in `publish.yml`) before any non-preview release.

## Cross-repository dependencies

| This repo item | Other repo | Other item | Relation |
|---|---|---|---|
| (pointer) | nodestro-studio | ST-052 (Dependabot policy: weekly groups, cooldown, manual merge; auto-merge prerequisites) | Full entry in studio |
| SRV-007 | nodestro-api | API-011 (observability, D-10) | Blocked by |
| SRV-013 | nodestro-runtime, nodestro-api | RT-008, RT-009, RT-020, API-013, API-023 (C-14 store throughput, C-05 usage latency) | Load test runs here; results feed into |
| SRV-014 | nodestro-runtime, nodestro-studio | RT-023, ST-028 (D-05) | One shared locking decision |
| (pointer) | nodestro-runtime | RT-001 (independent S-2 review) | SRV-004 keeps tool approvals off until it passes |
| (pointer) | nodestro-studio | ST-054 (Node.js 24 LTS in Q1 2027) | The image's `node-base` moves with it |
| (pointer) | nodestro-local-docker | `scripts/scan-image.sh` | Runs this repo's `scripts/scan-vulnerabilities.sh` at the pinned commit |
| (pointer) | nodestro-desktop, nodestro-local-docker | pin distance warning | They run this repo's `scripts/pin_distance.py` |
| – | nodestro-api / nodestro-runtime | API-005 / RT-010 (rotation of `NODESTRO_SECRET_KEY`) | Owned there; RUNBOOK limitation here |
| – | nodestro-api | API-010 (published workflow APIs not served) | Owned there; RUNBOOK limitation here |
| – | nodestro-api | API-019, API-001 (member management only via CLI; app-level hardening, A-09) | Owned there; RUNBOOK recommends proxy limits |
| (pointer) | nodestro-desktop | `scripts/check_server_copies.py` | This repo holds the source copies of the shared release scripts |
| (pointer) | nodestro-api | API-048 (server export jobs: per-tenant quota, retention; document `NODESTRO_SERVER_EXPORT_JOBS` in the RUNBOOK) | Owned there; SRV-004 keeps the switch off |

## CI access to private repositories

Keep the repository secret `NODESTRO_READ`; do not delete it. CI currently installs the sibling repositories anonymously
because they are public, and does not need the secret. When the repositories become private, CI authenticates again
with this read-only secret, passed only in the environment of the install steps (never in a global Git configuration,
a log or an image layer).

## Maintaining this file

- Add an entry when work is identified but not done in the current PR. Use the next free ID; IDs are never reused.
- Link a GitHub issue for anything concrete enough to be picked up; keep details in the issue, not here.
- When an item is finished, delete its entry in the PR that completes it and mention the ID in the PR description.
  Git history is the record; do not keep ticked checklists.
- Accepted risks stay listed with their reason until the risk is removed or re-evaluated.
- Re-review the whole file before each release and update the "Last full review" line.
- Security issues that are not yet fixed are described only in general terms here. Report details privately
  (GitHub private vulnerability reporting), never in this file or in public issues.
