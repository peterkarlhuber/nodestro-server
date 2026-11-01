# TODO: nodestro-server

> Open work for this repository: release blockers, known bugs, security follow-ups, technical debt and planned improvements.
> GitHub issues are the source of truth for details; this file is the entry point and summary.
>
> **Last full review:** 2026-11-01 against `master` at `42e95af`.

## Summary

| Priority | Count |
|---|---|
| P0 Critical | 0 |
| P1 High | 0 |
| P2 Medium | 12 |
| P3 Low | 5 |
| P4 Optional | 1 |

**Release blockers:** None for this repository. No server release or production deployment is approved; the
`v0.2.0-preview.1` server candidate may be prepared, but publishing needs an explicit owner decision (SRV-001).

The server image, compose stack, acceptance tests and runbook are in good shape for a supervised pilot on Linux
amd64. For production use, the gaps are operational: CI that works without secrets, vulnerability scans, consistent
backups, observability, reproducible builds, load tests and an external security review.

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
- **Next step:** After the next pin cascade, run `release.yml` again, record a Go/No-Go, and ask the owner whether to
  publish. Do not run `publish.yml` without that approval.

## Security

### SRV-002 · CI must not require the `NODESTRO_READ` secret

- **Priority:** P2 Medium · **Status:** Open · **Refs:** #25, backend audit D-08
- **What:** `ci.yml` and `release.yml` fail without the secret although all component repositories are public, so
  Dependabot PRs (#19) can never pass, and the CI comments still say "private".
- **Next step:** Make the token optional in both workflows and fix the comments (see #25).

### SRV-003 · Vulnerability scan of the image and its Python dependencies

- **Priority:** P2 Medium · **Status:** Open · **Refs:** #26, backend audit D-06
- **What:** CI scans the image only for secrets; resolved Python and OS packages are never audited. The same image
  definition serves Nodestro Local Docker.
- **Next step:** Add `pip-audit` on `pinned.txt` and an OS-package scan of the saved image to CI and `release.yml`.

### SRV-004 · External security review before any production use

- **Priority:** P2 Medium · **Status:** Needs external review · **Refs:** backend audit 2026-11-01 section 16
- **What:** The backend audit was internal. No external penetration test of a server deployment (OIDC login, tenant
  isolation, sandbox daemon, Bedrock role assumption) has been done. MCP is accepted only for a read-only pilot, and
  tool approvals (S-2) stay off outside an isolated pilot pending their own independent review.
- **Next step:** Commission an external test of a deployment built from a current candidate; keep MCP write tools and
  `NODESTRO_TOOL_APPROVALS` off until the respective reviews pass.

## Bugs and reliability

### SRV-005 · Consistent backup and restore of database plus data volume

- **Priority:** P2 Medium · **Status:** Open · **Refs:** #27, backend audit section 11
- **What:** `backup` (pg_dump) and the tar of `NODESTRO_DATA_DIR` are not taken at one point in time;
  `scripts/restore.sh` restores only the database; no restore drill outside CI.
- **Next step:** Document and script a quiesced, paired backup; restore and verify tenant files in the acceptance test.

## Architecture and modularity

None known. (The image definition here is shared with nodestro-local-docker by design; see its `docs/ARCHITECTURE.md`.)

## Performance

None known beyond the load test in SRV-013.

## Features and enhancements

### SRV-006 · Live Run Chat: acceptance test, runbook and studio pin

- **Priority:** P2 Medium · **Status:** In progress · **Refs:** #24
- **What:** Brings the Live Run Chat routes into the image (studio pin) with an acceptance test and runbook notes.
  Waiting for the owner's explicit merge approval and the pin cascade order.
- **Next step:** Merge after approval; re-pin `studio.json` to the studio merge commit first.

### SRV-007 · Monitoring section in the runbook

- **Priority:** P2 Medium · **Status:** Blocked (on nodestro-api observability, backend audit D-10) · **Refs:** backend audit D-10
- **What:** The runbook covers health checks only. There is no JSON log, request ID, metrics or readiness endpoint to
  document yet, and workers have no liveness signal besides `nodestro-server check`.
- **Next step:** When the API adds them, add a "Monitoring" section (what to scrape, alert on, log fields) and
  wire the dev stack's health checks to them.
- **Depends on:** nodestro-api (observability, D-10)

## Tests and quality assurance

### SRV-008 · Acceptance test for Bedrock without an operator role

- **Priority:** P3 Low · **Status:** Open · **Refs:** #29, Bedrock deployment analysis section 6
- **What:** Only an import check proves Bedrock is in the image; no test checks `provider.bedrock_not_available` for
  a tenant without a role, or that tool containers get no `AWS_*` variables.
- **Next step:** Add the offline test described in #29.

### SRV-009 · Dependabot: docker/setup-buildx-action 3 to 4

- **Priority:** P3 Low · **Status:** Blocked (on SRV-002) · **Refs:** #19
- **What:** Major version bump of an action; its `e2e` job fails only because the secret is missing.
- **Next step:** Re-run after SRV-002, review the v4 changes, merge if green.

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
- **Next step:** Test at least one production identity provider and a remote sandbox host before a pilot; record
  results in the runbook table.

### SRV-012 · Linux arm64 server image

- **Priority:** P3 Low · **Status:** Open · **Refs:** RUNBOOK "Releases and rollback"
- **What:** Only linux/amd64 is built and tested; the Dockerfile has an arm64 docker CLI checksum, and the `local`
  target is already built and tested on arm64 in nodestro-local-docker.
- **Next step:** Add an `ubuntu-24.04-arm` acceptance job.

### SRV-013 · PostgreSQL load test on target hardware

- **Priority:** P2 Medium · **Status:** Open · **Refs:** backend audit C-14, C-05
- **What:** Store throughput was measured only locally (still about 12 % below the pre-audit figure), and
  `/api/usage` grows linearly with the number of runs. Neither was measured on server hardware under load with
  several workers.
- **Next step:** Load test the compose stack (or a pilot setup) with realistic tenants, runs and workers; feed
  results back to nodestro-runtime/nodestro-api.

## Documentation

None known beyond SRV-007.

## Technical debt

### SRV-014 · Reproducible image builds

- **Priority:** P2 Medium · **Status:** Open · **Refs:** #28, backend audit D-05
- **What:** Third-party Python dependencies are resolved at build time inside version ranges; two builds of the same
  `studio.json` can differ.
- **Next step:** Hashed constraints file next to `studio.json`, installed with `--require-hashes` (see #28).

### SRV-015 · Development stack images by tag

- **Priority:** P3 Low · **Status:** Open · **Refs:** backend audit D-16
- **What:** PostgreSQL, Dex and Docker-in-Docker in `compose/compose.yaml` are referenced by tag (documented in the
  README); the image's own bases are pinned by digest.
- **Next step:** Pin them by digest and let Dependabot (docker ecosystem) keep them current.

### SRV-016 · Pin hygiene: merge commits and pin distance

- **Priority:** P3 Low · **Status:** Open · **Refs:** backend audit D-01
- **What:** `studio.json` pins `b8c6d48`, a studio branch head, although its comment promises a master merge commit;
  CI does not warn when the pin falls behind the latest studio platform commit.
- **Next step:** Re-pin to a merge commit in the next cascade; add a CI warning for pin distance.

## Later optimizations

### SRV-017 · Production deployment example

- **Priority:** P4 Optional · **Status:** Open · **Refs:** backend audit D-16 recommendation
- **What:** There is only the development stack. A production compose example (resource limits, external
  PostgreSQL, TLS proxy) or a Helm chart would make installations more uniform.
- **Next step:** Decide on the supported deployment form before writing one.

## Accepted risks

### SRV-018 · Unsigned preview images without provenance

- **Priority:** P2 Medium · **Status:** Accepted risk · **Refs:** backend audit D-09
- **What:** Images are not signed and carry no provenance attestation; the manifest and labels say `unsigned`.
  Accepted because nothing is released and preview versions are not meant for production data.
- **Next step:** Close (signing key, attestation in `publish.yml`) before any non-preview release.

## Cross-repository dependencies

| This repo item | Other repo | Other item | Relation |
|---|---|---|---|
| SRV-007 | nodestro-api | Observability (D-10) | Blocked by |
| SRV-013 | nodestro-runtime, nodestro-api | C-14 store throughput, C-05 usage latency | Results feed into |
| SRV-003 | nodestro-local-docker | Image scan (same image definition) | Covers both |
| – | nodestro-api / nodestro-runtime | Rotation of `NODESTRO_SECRET_KEY` | Owned there; RUNBOOK limitation here |
| – | nodestro-api | Server batches and test series stay `running`; published workflow APIs answer 405 | Owned there; RUNBOOK limitation here |
| – | nodestro-api | Member management only via CLI; app-level login rate limit and body size limit (A-02, A-09) | Owned there; RUNBOOK recommends proxy limits |
| – | nodestro-api | `check` does not warn about unknown tenant IDs in `NODESTRO_BEDROCK_TENANT_ROLES` | Owned there |
| – | nodestro-desktop | DSK-011 sync check of shared release scripts | This repo holds the source copies |

## Maintaining this file

- Add an entry when work is identified but not done in the current PR. Use the next free ID; IDs are never reused.
- Link a GitHub issue for anything concrete enough to be picked up; keep details in the issue, not here.
- When an item is finished, delete its entry in the PR that completes it and mention the ID in the PR description.
  Git history is the record; do not keep ticked checklists.
- Accepted risks stay listed with their reason until the risk is removed or re-evaluated.
- Re-review the whole file before each release and update the "Last full review" line.
- Security issues that are not yet fixed are described only in general terms here. Report details privately
  (see SECURITY.md or GitHub private vulnerability reporting), never in this file or in public issues.
