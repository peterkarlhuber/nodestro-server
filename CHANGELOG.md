# Changelog

## Unreleased

### Live run chat and steering (LRC-1, 2026-11-01)

- New acceptance test against the built image: the live run chat routes (`/api/runs/{id}/chat`, messages, the
  event stream) answer through the proxy chain, refuse a target that is not a team leader (404), keep other tenants
  out (404) and close with the run. Delivery to an orchestrator in the worker is covered by the runtime's PostgreSQL
  tests: the OpenAI-compatible model stub cannot answer orchestrator decisions (structured output with reasoning
  effort).
- RUNBOOK: how the live run chat works on a server, its limits and environment variables.
- `studio.json` pins studio `5e78721` (before: `b8c6d48`; the LRC-1 studio branch on top of Bedrock, to be replaced by
  the studio merge commit): runtime `b5b765f`, api `6890a2b`, sdk `ed512e7`, orkexa `3467940`.

### Studio pin: Amazon Bedrock branches (branch only, 2026-11-01)

- `studio.json` pins studio `b8c6d48` (before: `5f96652`), the studio branch with the Bedrock interface and the
  Bedrock branch pins: runtime `ac96c6f`, api `4e2c8cd`, sdk `3ca06b3`, orkexa `3467940` (boto3).

### Studio pin: final UX initiative state (2026-11-01)

- `studio.json` pins studio `5f96652` (before: `90f08ce`): the final UX initiative work (orchestration rounds view,
  per-language interface chunks, help and accessibility fixes). Backend pins unchanged: runtime `d141b8f`, api
  `db6a696`, sdk `4a97cef`, orkexa `6e69b9c`.

### Studio pin: PostgreSQL read performance, accessibility (2026-11-01)

- `studio.json` pins studio `90f08ce` (before: `561c655`): runtime `d141b8f` (pool checks only idle connections,
  read retry on a lost connection, autocommit single writes, PostgreSQL migration 0006 with partial find indexes),
  api `db6a696`, sdk `4a97cef`, and the UX work merged on studio master in between (accessibility, in-app docs).
- RUNBOOK: the maintenance note now covers migrations 5 and 6.

Backend audit (2026-11-01):

- `studio.json` pins studio `561c655` (before: `8db9981`). That studio pins runtime `6eacec1`, api `e16202d`,
  examples `e370567`, integrations `c221485`, sdk `76f7390` and orkexa `6e69b9c`, which carry the fixes of the
  internal backend audit. This is not an external pentest or certification.
- New operator commands manage tenant members: `nodestro-server members`, `set-role`, `remove-member` and
  `revoke-sessions`.
- New settings: `NODESTRO_WORKER_CLEANUP_SECONDS`, `NODESTRO_DATABASE_POOL_SIZE`,
  `NODESTRO_DATABASE_STATEMENT_TIMEOUT`, `NODESTRO_DATABASE_IDLE_IN_TRANSACTION_TIMEOUT` and `NODESTRO_RUN_THREADS`.
- Behavior changes:
  - `/api/health` answers 503 when the database is unreachable.
  - Logins are bound to the browser.
  - The access log is redacted.
  - The API reference needs a login.
  - The studio is served gzip-compressed with cache headers.
- `docs/RUNBOOK.md` and `README.md` are updated accordingly: members, configuration, health checks, environment
  images, upgrade notes (PostgreSQL migration 5 builds an index at start) and security notes. The docs now say
  the component repositories are public.
- MCP, unattended MCP and the tool approval switches stay off by default. The accepted MCP pilot (server `d89aafc`)
  and the S-2 pilot B pin (`c497bfe`) are not changed; their acceptance does not cover this version.

Example library format 2 (2026-11-01):

- `studio.json` pins studio `8db9981` (before: `ba45ab3`). That studio pins examples `5e2d532` (0.3.0), api `870ba5f`
  and sdk `d71fadd`; runtime `58cec5c` and integrations `cb8c2da` are unchanged. The 24 examples are reworked
  (teams, knowledge files, optional read-only MCP integrations with an offline mode); copying an example creates its
  parts as workflows and stores its knowledge files.
- No server change; MCP, unattended MCP and the tool approval switches stay off by default.

Security fixes from the independent MCP re-review R-1/R-2 (2026-11-01):

- `studio.json` pins studio `ba45ab3` (before: `19a1127`). That studio pins runtime `58cec5c`, api `05e449d`,
  examples `3429f5b`, integrations `cb8c2da` and sdk `7f60f9b`. They carry:
  - R-1: an MCP call is decided by an administrator when its stored or current classification is destructive; a
    reclassification invalidates pending and approved but not yet executed approvals (also for paused runs), and the
    call is checked again right before it is sent (`tool.approval_stale`);
  - R-2: `memory` is a reserved tool name; a tool stored under it before is never run.
- No server change; the tool approval switches stay off by default.

Security fixes from the independent MCP review (2026-11-01):

- `studio.json` pins studio `19a1127` (before: `e47081f`). That studio pins runtime `f71086a`, api `476cfc0`,
  examples `69e5e65`, integrations `31a7020` and sdk `7b795f7`. They carry the fixes of the independent MCP review:
  - per-call approvals hold in agent tests and the tool panel; free agent configurations need `edit`;
  - destructive MCP calls are decided by administrators;
  - no credentials in MCP server addresses (stored ones are cleaned and their server switched off at start);
  - MCP answers are size limited while they are read;
  - L-2 to L-8.

  They also carry the offline worker fix F5. Nothing is switched on: `NODESTRO_TOOL_APPROVALS` and MCP stay as
  configured. The first pilot is limited to an isolated test instance.

- RUNBOOK: the "Not yet" list states what published APIs, batches and test series do on a server today (S-2 pilot
  finding F4).

Runs paused at a tool approval (AO M6b, behind a switch, 2026-11-01):

- `studio.json` pins studio `e47081f` (before: `24bac8e`). That studio pins runtime `c86781b` and api `ae6cecd`.
  With `NODESTRO_TOOL_APPROVALS=1` and the new `NODESTRO_TOOL_APPROVAL_CHECKPOINTS=1` (both off by default) a tool
  call that waits for a person pauses the run and frees its worker; the decision continues it on any worker, exactly
  once, and every worker runs the deadline sweep (once before serving, then periodically). Nothing changes while
  the switches are off.

Security fix for tools in workers (S-2 pilot finding F1, 2026-11-01):

- `studio.json` pins studio `24bac8e` (before: `cf4b070`). That studio pins runtime `6ac4ae3` and api `ebd99b3`.
  Every worker now sees tool changes and deletions made through the API at its next lookup, without a restart, and a
  running step refuses a tool whose version changed or was deleted since it started, also after an approval or
  advance approval for the old version. Tool approvals stay off by default.

Adaptive orchestration M6b in the studio and the latest components (2026-11-01):

- `studio.json` pins studio `cf4b070` (before: `4e0dc58`). That studio pins runtime `081705d`, api `ee67eac` and
  orkexa `a06185d`. They bring orchestrators with dynamic teams (staffing, parallel teams, team parameters; all off
  per orchestrator by default), approval steps inside orchestrated teams that pause instead of cancelling, the run
  view of an orchestrator (team over time, outcomes, limits and costs, save the team as a template) and the welcome
  page. No new server switch; tool approvals stay off by default and this server configuration sets none of them.

MCP integration complete in the studio and the latest components (2026-11-01):

- `studio.json` pins studio `4e0dc58` (before: `66fe676`). That studio pins runtime `1bc3924` and api `2948bb3`. They
  bring MCP sign-in (OAuth), local MCP servers in the sandbox container, the operation view, reading a service's
  listed resources through one approved tool, and Nodestro as an MCP server for published APIs. They also carry the
  tool approval warnings (S-2, R1) and adaptive orchestration M6a merged since `66fe676`. Nodestro's MCP server stays
  off unless the operator sets `NODESTRO_MCP_SERVER=1`; unattended MCP use stays off unless `NODESTRO_MCP_UNATTENDED=1`
  (both need the security acceptance); tool approvals stay off by default. This server configuration sets none of them.

Local Docker sessions, hardened gateway and the latest components (2026-11-01):

- `studio.json` pins studio `66fe676` (before: `d71780a`). That studio pins runtime `a13f894` and api `c58d5de`. They
  bring the hardened sandbox gateway of the `local` target (runtime PR #47: image, connection and build-queue limits,
  seccomp check, strict `ca.pem`, digest-pinned sandbox bases) and Local Docker browser sessions on a random
  `*.localhost` host name with lifetime and logout plus the Host port check (api PR #29). They also carry the
  adaptive orchestration (M2 to M5) and tool approval (S-2) work merged since `d71780a`; tool approvals stay off by
  default.

Connected MCP services in the studio (2026-10-31):

- `studio.json` pins studio `d71780a` (before: `0609fbb`). That studio pins api `a06ccea` (the `/api/mcp` routes,
  MCP WP-3) and sdk `8fcb94d`, and adds the Tools › Connected services page (WP-4). Runtime stays at `8597544`. MCP
  services stay off until an administrator adds a server; nothing is enabled by default.

Reproducible base images (K4 of the internal cross-check):

- `image/Dockerfile` takes `python:3.13-slim` and `node:22-bookworm-slim` by the digest of their multi-platform index
  (`PYTHON_IMAGE`, `NODE_IMAGE`; `NODE_VERSION` is gone). A rebuild of the same commits now uses the same operating
  system layers on amd64 and arm64. The model stub in `compose/compose.yaml` is pinned the same way.
- CI (`lint`) fails when a `FROM` or the compose stub names a base image without a digest.

Sandbox gateway security fixes (2026-10-31):

- `studio.json` pins studio `0609fbb` (before: `c4b3708`). That studio pins runtime `8597544`. Its sandbox gateway,
  which runs in the `local` target's gateway container, parses request heads strictly (request smuggling fix,
  runtime PR #33) and refuses sandboxes when the Docker daemon cannot enforce resource limits (runtime PR #37).
  The studio commit also carries the studio work merged since `c4b3708`.

Nodestro Local Docker target (2026-10-31):

- `image/Dockerfile` builds two images from one definition: target `server` (the default, unchanged contents) and
  target `local` for Nodestro Local Docker (profile `local-container`, SQLite in `/var/lib/nodestro`, entry point
  `nodestro-local`, `DOCKER_HOST` pointing at the sandbox gateway's socket, `DOCKER_BUILDKIT=0`). They share the
  stages that fetch the studio at its pinned commit, build the interface, install every component and collect the
  license texts (`image/finalize.sh`); only the last stages differ. The local image has no PostgreSQL client and no
  server extras.
- The repositories are public, so the `nodestro_read` token is optional in the Dockerfile (still used when given).
- `scripts/build-image.sh` takes `NODESTRO_TARGET`; CI also builds the `local` target and checks its imports.
- `studio.json` pins studio `c4b3708` (before: `78710ce`).

License texts (2026-10-31):

- The image has `/opt/nodestro/licenses/`: Nodestro's license, the license texts of the npm packages built into the
  studio interface (`scripts/npm_licenses.mjs`, shared with nodestro-desktop) and a README that names where the
  Python packages', the Debian packages' and the docker CLI's licenses are.
- `.dockerignore` limits the build context to what the Dockerfile copies (keeps `compose/.secrets` out of it).

Release candidate v0.2.0-preview.1 (2026-10-31):

- Building and publishing are separate: `release.yml` only builds and checks a candidate (run by hand with the
  version; read-only token, no tag, no push, no release). The new `publish.yml` is the only workflow that publishes:
  run by hand with a passed candidate's run ID and the confirmation `publish <version>`, it pushes exactly the tested
  image (checked by image ID) under the version tag and creates a draft pre-release. Before, a pushed tag pushed the
  image to ghcr.io without a further approval.
- `scripts/scan_secrets.py` scans the saved image (every layer) and the release files for credentials and for the
  exact build token; CI scans its image on every change. Tests in `scripts/test_scan_secrets.py`.
- The image carries its version and the labels `dev.nodestro.channel` (`preview` for a pre-release version) and
  `dev.nodestro.signing=unsigned`; the manifest names the image by its ID and has a `channel` field.
- `studio.json` moves to studio `78710ce`.
- `docs/RUNBOOK.md`: the tested system requirements and the three release steps.

Releases (plan M6, 2026-10-31):

- `.github/workflows/release.yml`: a tag `v*` builds the image and runs every acceptance test against it. Only then
  is the image pushed to `ghcr.io/peterkarlhuber/nodestro-server:<tag>` and a draft release created. A manual run
  builds and tests without publishing.
- `scripts/release-manifest.sh` runs `scripts/release_manifest.py` inside the image. It writes
  `release-manifest.json` (image digest, studio and component commits, license inventory of the image's Python
  packages and the studio's npm packages, signing state "unsigned") and `SHA256SUMS`. CI writes it on every change
  as a dry run.
- The image keeps the studio commit, `versions.json` and `package-lock.json` in `/opt/nodestro/meta`.
- `studio.json` moves to studio `5a1cf56` (api `a08c9c3`, sdk `e508e6b`: Architect agents get the configured default
  model as quality judge).
- `docs/RUNBOOK.md`: releases, deploy by digest, rollback with the pre-migration backup, supported platforms.

The first server (desktop/server plan, PR-12, 2026-10-31):

- Image `nodestro-server` built from a pinned nodestro-studio commit (`studio.json`): the built studio, the API with
  the `server` extra, the runtime with the `postgres` extra, the docker CLI 29.9.2 (checksum-verified),
  `pg_dump`/`pg_restore`, `tini`; runs as user 10001. Private repositories are read with a BuildKit secret.
- Development and test stack (`compose/compose.yaml`): PostgreSQL 17, Dex v2.44.0, Docker-in-Docker 29.9.2 with
  TLS as the sandbox daemon, an OpenAI-compatible model stub, `migrate`, `api` and `worker`; every port on
  127.0.0.1. `compose/extra-ca.yaml` for TLS-inspecting proxies.
- Scripts: `dev-secrets.py` (random secrets and dev passwords), `build-image.sh`, `restore.sh`, `e2e.sh`.
- End-to-end acceptance tests (`tests/e2e`) and the runbook (`docs/RUNBOOK.md`).
