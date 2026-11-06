# Changelog

## Unreleased

### Studio pin: MUP-ONA B2 cascade (2026-11-07)

- Pins nodestro-studio 9c0a6bd (studio #149): runtime d9c3d6e (orkexa 028faa1 with the MUP-ONA B2 SQLite backends,
  Axentra 60d83b3 with the A8 security test vectors, a reindex switch that embeds what its last round left), api
  44212bc (`agent.VectorError` answers 422), sdk bda96c1.
- RUNBOOK configuration: the PDF reading limits `NODESTRO_PDF_TIMEOUT_SECONDS`, `NODESTRO_PDF_MAX_PAGES`,
  `NODESTRO_PDF_MAX_CHARS` and `NODESTRO_PDF_MAX_MEMORY_MB` (MUP-ONA A1, PS-1; memory limit on Linux only), in effect
  since studio 27f8bd4.

### Operations: TODO abatement round 6 (2026-11-07)

- Browser test (SRV-010): `scripts/browser-e2e.sh` runs the development stack behind Caddy as the TLS proxy
  (`tests/e2e/tls-proxy.yaml`, `https://localhost:8443`) and `tests/e2e/browser.mjs` in Chromium: a setup-link login
  through Dex, the `__Host-nodestro-session` cookie flags, HSTS, the signed-in studio without console errors, sign out
  and a second login, and the refusals (untrusted certificate, plain http, wrong password, no tenant, a sign-in code
  in another browser). CI runs it in the `e2e` job; Dex's development config accepts the https redirect address
  when `NODESTRO_TLS_ORIGIN` is set. Firefox and Safari remain untested (SRV-010, now P3).

### Operations: TODO abatement round 5 (2026-11-07)

- RUNBOOK "Semantic knowledge search": what to do when pgvector was installed after migration `0010` (nodestro-runtime
  RT-048): one SQL query shows whether pgvector ranks the vectors, with the command for each state (`installable`,
  `other_schema`, `unavailable`); then restart the API and worker processes, no reindex. The install hint names the
  schema for `NODESTRO_DATABASE_SCHEMA`. `nodestro-server check` now prints `warning: knowledge.pgvector_<state>` with
  the command to run (nodestro-api #102, through the studio pin below).

### Studio pin: TODO abatement round 5 (2026-11-07)

- Pins nodestro-studio 27f8bd4 (studio #146 and #147: api 63af1df with the usage report by provider region, the
  pgvector warning in `check` and MUP-ONA A1; sdk 4596be3; runtime de56875).

### Operations: TODO abatement round 4 (2026-11-07)

- The development stack and `compose/production.example.yaml` check the API with `GET /api/ready` (readiness) and
  set `NODESTRO_LOG_FORMAT=json`; a new acceptance test checks readiness, request ids and the JSON log lines.
- `NODESTRO_POSTGRES_IMAGE` replaces the development stack's database image for tests on other PostgreSQL major
  versions; the RUNBOOK records what PostgreSQL 16 and 18 did.
- The worker health check in `compose/compose.yaml` and `compose/production.example.yaml` runs
  `nodestro-server worker-health` against the heartbeat file `NODESTRO_WORKER_HEARTBEAT_FILE=/tmp/nodestro-worker.json`
  (nodestro-api API-011), so a hung worker turns unhealthy; the RUNBOOK explains the exit codes and that workers build
  server export packages when `NODESTRO_SERVER_EXPORT_JOBS` is switched on.

### Studio pin: TODO abatement round 4 (2026-11-07)

- Pins nodestro-studio f69020a (studio #143: runtime f26dac4 with LD-020, Bedrock regions in usage, registry facts
  and `pgvector_status()`; api 77f53be with queued export builds and the worker heartbeat; integrations c3623bd with
  bounded OCR).

### Studio pin: TODO abatement round 3 (2026-11-06)

- Pins nodestro-studio ee3f378 (studio #142: Settings → Members, export delete, runtime b06b371 with the semantic
  reindex as a server job, api 7142761 with member routes, idle tenant contexts, export quota and chat file
  retention in the worker).
- RUNBOOK: members in the studio, `NODESTRO_TENANT_IDLE_MINUTES`, `NODESTRO_SERVER_EXPORT_TENANT_QUOTA_BYTES` and
  reindex jobs.

### Operations: MUP-ONA security documentation

- RUNBOOK "Client addresses behind a reverse proxy" (MUP-ONA A3, PS-3): `NODESTRO_BEHIND_PROXY`,
  `FORWARDED_ALLOW_IPS` and `NODESTRO_REQUIRE_CLIENT_ADDRESS`, what `check` and `api` report, `X-Forwarded-For` in
  nginx, Caddy and Traefik, the per-key count of failed published API keys and the accepted residual risk.
  `compose/production.example.yaml` gives Caddy a fixed address and sets `FORWARDED_ALLOW_IPS` and
  `NODESTRO_BEHIND_PROXY=1` for the API. The new variables take effect with the studio pin that contains
  nodestro-api MUP-ONA A3.
- RUNBOOK "Database roles": Axentra and the table owner (MUP-ONA A6, PS-6): this server checks the runtime role
  itself and passes Axentra `allow_table_owner` from `NODESTRO_AXENTRA_ALLOW_SUPERUSER` (unchanged); Axentra on its
  own refuses an owner role in production unless `database.allow_table_owner = true`.
- RUNBOOK: how to keep `NODESTRO_MODEL_ENDPOINTS` narrow (MUP-ONA A7, PS-7, accepted risk): exact origins only,
  never internal services or metadata addresses, model servers on their own network segment.

### Studio pin: TODO abatement round 2 (2026-11-06)

- Pins nodestro-studio 5c0fbd8 (studio #140): api 56fa762 (idempotency reservation, usage period read, assistant
  file retention, tool version history, library copy memory space), sdk 1306cbe; settings change marks, example
  sample files in the run dialog, sample data badge, tool adoption diff.

### Studio pin: TODO abatement round (2026-11-06)

- Pins nodestro-studio 39fb164 (studio #136): orkexa 1b61fda, runtime 3d69702, api a3bd875, examples 82d894b,
  integrations 1e73e29, sdk 7714de0 (0.3.0): the TODO abatement round across the platform (see each repository's
  CHANGELOG).

### Operations: TODO abatement round (2026-11-06)

- CI and `release.yml` scan the server image and the `local` image for known vulnerabilities
  (`scripts/scan-vulnerabilities.sh`: pip-audit on `pinned.txt`, Trivy on the saved image by digest); any Python
  vulnerability and any fixable HIGH or CRITICAL OS finding fails the build; the reports are kept as artifacts.
- `scripts/backup.sh` takes the database and the data volume at one point in time (API and worker stopped) with a
  manifest of SHA-256 checksums; `scripts/restore.sh` restores a manifest (database, data volume, `files verify`
  for Axentra's storage) after checking every checksum, or a dump as before.
- New acceptance tests: a paired backup restores the tenants' files; Bedrock is unavailable without an operator role
  although the server has AWS credentials, and tool containers get no AWS variables; a tenant's semantic index is
  built through an embedding endpoint (the model stub now answers Ollama's `/api/embed`) and searched with pgvector.
- CI runs the acceptance tests on Linux arm64 too, warns when the studio pin lags behind studio master
  (`scripts/pin_distance.py`), and validates `compose/production.example.yaml`, a production example (not a supported
  deployment form; RUNBOOK "Production example").
- The image's base images are `FROM` lines that Dependabot updates; the release manifest lists bundled binaries
  (the docker CLI) with their licenses.
- `tests/e2e/load.py`: a load test of the development stack (RUNBOOK "Load test").
- RUNBOOK: the API's login start limit (`NODESTRO_LOGIN_STARTS_PER_MINUTE`) and `FORWARDED_ALLOW_IPS` behind a proxy,
  `nodestro-server assistant backfill-owners`, `/api/ready`, `X-Request-ID` and JSON logs
  (`NODESTRO_LOG_FORMAT=json`), batch leases and the access audit trail (`GET /api/access-audit`); they take
  effect with the next studio pin (nodestro-api API-002, API-004, API-006, API-011, API-057).

### Studio pin: settings, attachments and providers (2026-11-06)

- Pins nodestro-studio 58bb17d (studio #135): orkexa 566aa3c (model limits, live reasoning, resumable local setup,
  valid Chat Completions histories for Ollama), runtime 62527d1, api a799912 (assistant file attachments, output
  limits, local model readiness, publication overview), examples 97bf788, integrations 2e975ad, sdk b3ae8c7.

### Studio pin: product findings of the manual review (2026-11-05)

- Pins nodestro-studio a1acb1b (studio #127): nodestro-runtime 57b40d2 (the strict offline mode refuses cloud models
  outside runs too; orchestrators with models without a reasoning effort; an expired budget decision ends a run
  `failed`), nodestro-api f796916 (no price check in the strict offline mode; batches and test series on a server
  follow their runs from the database), nodestro-examples f015a4d, nodestro-integrations 9a5c955, nodestro-sdk
  8c4c9ff; UI texts and in-app docs without internal switch names.
- RUNBOOK: batches and test series are no longer listed as unsupported; only a stopped API process still leaves one
  `running` (API-006).

### Studio pin: backend audit round 3 and UX round 3 (2026-11-04)

- Pins nodestro-studio 2c072d7 (studio #123, #124): nodestro-api 5ee13f7 (export jobs on a server only with the
  operator opt-in `NODESTRO_SERVER_EXPORT_JOBS=1`, one build at a time, `NODESTRO_SERVER_EXPORT_MAX_BYTES`; tenants
  without the `install` permission see no machine details in Local models), nodestro-runtime 40c8c06, orkexa
  e9c2147, axentra 0a1d1cc (API keys answer 403 while their creator lacks the rights), nodestro-examples 64e534a,
  nodestro-integrations 8687e09, nodestro-sdk abdf686.

### Studio pin: checked key figures (2026-11-04)

- Pins nodestro-studio 0a6a320 (studio #120: key figures that a condition decides on or that report money or days must come from a tool, and the runtime checks them (`OutputField.source`, built-in `table_totals`); local Ollama agents with a structured result call their tools (orkexa #45, #46); production-downtime decides on the computed 4.62 % instead of an estimate).

### Studio pin: local AI follow-up (2026-11-04)

- Pins nodestro-studio f9e4a91 (studio #118, #119): nodestro-runtime 7cb9b4b (in the CPU saving mode the quality judge
  of a local thinking model also answers without the thinking phase; a local model server gets 60 minutes per request
  instead of the SDK's 10), nodestro-api 5951197, nodestro-examples 36488a6, nodestro-integrations 40d6053,
  nodestro-sdk e58249b; orkexa stays at 4ec738c. The browser smoke test now covers the per-agent model plan and the
  local hardware panel.

### Studio pin: local AI optimization (2026-11-03)

- Pins nodestro-studio 74a9aa6 (studio #117): orkexa 4ec738c (robust hybrid fusion of knowledge search),
  nodestro-runtime 3006ce0 (CPU saving mode for thinking models, context window and hardware advice), nodestro-api
  c2a2ad3 (per-agent local models when copying an example), nodestro-examples be55542, nodestro-integrations f5a25d6.
  On the server the speed measurement of local models is refused for tenants (the operator's models), and the saving
  mode applies only to Ollama endpoints that report CPU use; an endpoint whose hardware is unknown is never reduced.

### Studio pin: local models chain (2026-11-03)

- Pins nodestro-studio 97564f4 (studio #115): orkexa 71f8aaf, nodestro-runtime 90ba97b, nodestro-api a24f32b,
  nodestro-examples 7b79fde, nodestro-integrations 3026776. The server gets the European model catalog entries and the
  "prefer European models" setting, thinking off at effort "low" for local thinking models, and the optional mDenseOn
  embedding build (the image now carries `gguf` and `numpy` through orkexa `[convert]`). The server runs no local model
  server; Ollama endpoints still come through `NODESTRO_MODEL_ENDPOINTS`.
- Restores (`scripts/restore.sh`, the upgrade test, the RUNBOOK) run `scripts/restore_dump.py`: in one transaction it
  drops the owner role's tables, views and sequences that are not in the dump, then applies the dump. The runtime's
  migration `0010` adds `nodestro_chunk_vectors` with a foreign key to `nodestro_chunks`; restoring the backup taken
  before it (a rollback) stopped at `DROP CONSTRAINT nodestro_chunks_pkey` ("other objects depend on it").

### PostgreSQL with pgvector for semantic knowledge search (2026-11-03)

- The development stack's `postgres` and `db-roles` use `pgvector/pgvector:0.8.7-pg17`, pinned by the digest of its
  multi-platform index (before: `postgres:17` by tag). It is the official PostgreSQL 17 image plus pgvector, so an
  existing data volume is kept as it is. The CI check of digest pins covers it.
- `compose/postgres/roles.sql` installs the extension (`CREATE EXTENSION IF NOT EXISTS vector`) as the superuser where
  it is available. pgvector is not a trusted extension: the owner role cannot install it, so nodestro-runtime's
  migration `0010` alone would leave it out. With it, PostgreSQL ranks the vectors of semantic knowledge search;
  without it the runtime does.
- Restores (`scripts/restore.sh`, the upgrade test, the RUNBOOK's steps) leave extensions out of `pg_restore`: as the
  owner role, `--clean` stopped at `DROP EXTENSION vector` ("must be owner of extension vector") for every backup of
  a database with pgvector.
- New acceptance test: the database has pgvector 0.8.7 and it works. RUNBOOK: new section "Semantic knowledge search
  and local models" (pgvector for your own PostgreSQL, no local model server in the server, Ollama endpoints through
  `NODESTRO_MODEL_ENDPOINTS`), install, database roles, restore and tested requirements updated. docs/TODO.md: SRV-015
  narrowed, SRV-020 (semantic search at server scale) added.

### Backend audit round 2: pins and worker health check (2026-11-03)

- `studio.json` pins studio `997f485` (before: `83d8998`; the merge commit of studio #110): nodestro-runtime `140d479`
  (`migrate --backup-dir` no longer deadlocks on databases from before migration checksums, OPS2-01; approvals inbox
  by indexed status, pooled connections checked after a database restart, keyset run pages), nodestro-api `84ca99d` (security headers, request body limit, keyset run
  list, idempotent run starts, uniform error bodies, origin checks), Axentra `a872242` (tenant-scoped overview,
  limited backdating), orkexa `bc8c4ed` (sandbox calls stopped on timeout and cancel), nodestro-examples `8499edf`,
  nodestro-integrations `e2582cc` and nodestro-sdk `d68c67b`.
- The worker health check in `compose/compose.yaml` runs `nodestro-server check --skip-identity-provider`: since
  nodestro-api `84ca99d`, `check` also fetches the identity provider's discovery document, which workers do not use.
  Without the option each worker would poll the identity provider every 10 seconds and turn unhealthy while it is down.
  RUNBOOK updated.
- `studio.json` pins studio `b7c8af2` (merge commit of studio #111, UX round: frontend only; the backend pins of
  `997f485` are unchanged).
- `studio.json` pins studio `6e94ae4` (merge commit of studio #112: nodestro-api `7c195ed`, nodestro-sdk `f44d156`).
  Exporting a project no longer answers 500 because the image installs no test tools (nodestro-api #77).
- New CI job `upgrade` (`.github/workflows/upgrade.yml`, `tests/e2e/test_upgrade.py`): the previous release
  (`tests/upgrade-from.json`, server `5bc7b82` of the `v0.2.0-preview.1` candidate, with its own compose file and
  image) gets data and a backup, then is upgraded as the RUNBOOK says (`migrate --backup-dir`, bounded in time so that
  a hang like OPS2-01 fails), rolled back with the backup that `migrate` wrote, upgraded again, and its old backup is
  restored by the current release. Runs when the pins, the stack or the test change, weekly and on demand (SRV-021).

### Nodestro–Axentra migration close-out (2026-11-03)

- `studio.json` pins studio `83d8998` (before: `139bce3`; the merge commit of studio #107): nodestro-runtime `bcfea7f`
  (static tenant SQL check gaps closed, #89 and round 4; a suspended tenant's tool generation jobs stop and start no
  install, NF-1 and R4-7), Axentra `2767a2e` (invitation tokens kept out of URLs and logs; the GET OIDC start refuses
  invitations), orkexa `0861c1b`, nodestro-api `f21fd6a` and nodestro-sdk `d12ba72`. No server code changes.

### Docker-first follow-up (2026-11-02)

- `studio.json` pins studio `139bce3` (before: `6351ad3`; the merge commit of studio #105): nodestro-runtime `958be1d`
  (source builds of Python libraries are refused on the server, R-1: plans use wheels only; container shape checks,
  R-5; MCP container deadline 15 minutes; tool adoption, which the server refuses with `tool.adoption_desktop_only`),
  nodestro-api `b8139b0`, nodestro-examples `8c338d3`, nodestro-integrations `e71bf55`; orkexa stays `dec66eb`.

### Python 3.11 minimum (2026-11-02)

- Python 3.11 is now the minimum (3.10 reached end of life in October 2026): ruff `target-version = "py311"`; the image
  already runs 3.13.
- `studio.json` pins studio `6351ad3` (before: `f79c11d`; the merge commit of studio #103): orkexa `dec66eb`,
  nodestro-runtime `51262a2`, nodestro-api `ef04cb4`, nodestro-examples `3f91300`, nodestro-integrations `6e0c9e6`,
  all with Python 3.11 as the minimum; axentra stays `024da57`.

### Pins: Axentra migration completion and security review fixes (2026-11-02)

- `studio.json` pins studio `f79c11d` (before: `d2724c2`; the merge commit of studio #102, which contains d2724c2): axentra `024da57`,
  orkexa `3364fb8`, nodestro-runtime `0369132`, nodestro-api `3e0a874`, nodestro-examples `b7a1d65`,
  nodestro-integrations `0de02d0`. The security review fixes below take effect with this pin.
- SRV-020 is closed (fixed in nodestro-api `df97118`: an empty archive while nothing is stored). Its acceptance test now
  checks the other side: with files recorded, a missing storage directory makes `backup` fail instead of writing an
  empty archive.

### Security review fixes, documented

- Members: an e-mail address no longer names a user by itself in `set-role`, `remove-member` and `revoke-sessions`
  (SR-10): on a terminal the command shows the user with their identity and asks for the user id; otherwise it stops
  with `identity.user_confirm`. The acceptance tests pass user ids.
- Key rotation (step 3): `secrets reencrypt` also re-encrypts Axentra's own columns; the start checks their key ids
  and that each key decrypts stored values (SR-04, SR-05).
- Input files (step 6): `files verify` fails on leftovers (`orphans`, `unreferenced`), `files cleanup` removes them;
  run it after switching back from `volume` (SR-09). The volume catalog is locked across processes (SR-08).
- Backups: an empty storage archive before the first upload; a clear error when `pg_dump` runs without the owner
  role. A duplicated sentence in the backup paragraph is gone.

### Run budget decisions (BUDGET-1, 2026-11-02)

- `studio.json` pins studio `d2724c2` (the merge commit of studio #101, with BUDGET-1 from studio #97 and the server
  start-up fix of nodestro-api #65): nodestro-runtime `bf9af7d`, nodestro-api `dde77f5`, orkexa `3364fb8`.
- RUNBOOK: section "Run budget decisions" and the operator cap `NODESTRO_MAX_RUN_BUDGET_USD`.
- New end-to-end test: a run in the worker pauses for a budget decision, a raise in the API process continues it in
  a worker, the request is sent once, another tenant sees nothing.
- Sandbox e2e tests wait for the Docker check: the API's monitor must report `approved` (`GET /api/sandbox/status`)
  before a tool is saved and after the sandbox daemon is restarted; a run refused with `docker-checking` while the
  worker's own check still runs is started again. Since the start-up preflight, the self-test runs in the background.
- The compose sandbox daemon is built from `docker:29.9.2-dind` plus `apparmor` and a `dockerd` wrapper that unsets
  `container` (`compose/sandbox/`): on an AppArmor host the stock image started tool containers unconfined, which the
  self-test (orkexa #34) refuses. RUNBOOK: the sandbox daemon must confine its containers on AppArmor hosts.
- The sandbox daemon's base `docker:29.9.2-dind` is pinned by its index digest and `apparmor` by version
  (`4.1.7-r1`); CI's digest check covers `compose/sandbox/Dockerfile` too.

### Every Axentra switch on, end to end (development stack only)

- `compose/all-switches.yaml` (with `compose/axentra/axentra.toml`) turns every Axentra migration switch on for
  `migrate`, API and worker; `scripts/dev-secrets.py` also writes `axentra_keyring` and `metrics_token`.
  `NODESTRO_E2E_ALL_SWITCHES=1 scripts/e2e.sh` layers it and runs `tests/e2e/test_all_switches.py` too; CI runs the
  acceptance tests a second time that way. New acceptance test for `suspend-tenant` / `resume-tenant` (both modes).
  No switch is approved for production by this.

### Pins: Axentra completion (2026-11-02)

- `studio.json` pins studio `1db50b8` (before: `32ca327`; the merge commit of studio #94): axentra `f6ae01d`,
  nodestro-runtime `95114ae`, nodestro-api `961afef`, nodestro-examples `9cdc1f5`, nodestro-integrations `8ecfb00`.
  The RUNBOOK entries below that waited for "the next runtime/api pins" take effect with this pin.

### Identity completion, documented

- RUNBOOK: `suspend-tenant` / `resume-tenant`; in `axentra` identity mode Axentra runs the login and decides
  permissions from versioned role definitions; `FORWARDED_ALLOW_IPS` behind the proxy (login start rate limit).
  Needs the next nodestro-api/runtime pins.
- RUNBOOK: metrics endpoint (`NODESTRO_METRICS_TOKEN`) with alerts, `axentra status`, the new switches
  `NODESTRO_AXENTRA_RUN_USAGE` and `NODESTRO_AXENTRA_NOTIFY`, and the start check and way back for `axs1` secrets
  (takes effect with the next runtime/api pin).
### Input files in Axentra's storage, documented (M8, 2026-11-02; off by default)

- RUNBOOK: `NODESTRO_FILES_BACKEND`, `NODESTRO_FILES_SOURCE_REMOVAL`, `NODESTRO_FILES_SOURCE_RETENTION_DAYS`, the
  `files migrate|verify|remove-source|export-volume` procedure (step 6 of switching on) and backups of Axentra's
  local storage directory or S3 bucket with `files verify` after a restore. Needs the nodestro-runtime/api pins
  with M8; nothing is switched on.
### Separate database roles (dbinfra)

- The development stack no longer runs the server as the superuser: the new one-shot `db-roles` service
  (`compose/postgres/roles.sql`, idempotent, on every start) creates `nodestro_owner` (owns the tables, `BYPASSRLS`
  for `pg_dump`; used by `migrate`, backups and `scripts/restore.sh` through the new `database_migration_url` secret)
  and `nodestro_app` (API and worker: no superuser, no `BYPASSRLS`, owns nothing). A stack created before is moved
  over: the tables the superuser owned go to `nodestro_owner`, and `scripts/dev-secrets.py` rewrites a `database_url`
  that names the superuser. `NODESTRO_AXENTRA_ALLOW_SUPERUSER` is gone from the compose file.
- RUNBOOK: new section "Database roles" (attributes and why, `roles.sql` or the statements by hand,
  `nodestro-server db roles` and `db grant-runtime-role`, moving an existing installation), the
  `NODESTRO_DATABASE_MIGRATION_URL` setting, backup and restore as the owner role, `max_connections` with Axentra on
  (one pool per process). TODO SRV-019 updated.
- Needs a `studio.json` pin with nodestro-runtime and nodestro-api of the same change (`NODESTRO_DATABASE_MIGRATION_URL`,
  the role checks); with an older image, `migrate` would run as `nodestro_app` and fail.

### Axentra platform services, documented (2026-11-02)

- `studio.json` pins studio `32ca327` (before: `bae25eb`; the merge commit of studio #93): nodestro-runtime `95dbdfa`
  and nodestro-api `bda8148` with the Axentra platform services, all off by default. The image (Python 3.13) now
  contains the `axentra` package through `nodestro-runtime[postgres]`.
- RUNBOOK section "Axentra platform services (optional, off by default)": the `NODESTRO_AXENTRA*`,
  `NODESTRO_SECRETS_FORMAT` and mirror switches, switching on with one backup, a role without `BYPASSRLS`, key rotation
  with `nodestro-server secrets reencrypt`, `axentra reconcile`, the identity backend (`NODESTRO_IDENTITY_BACKEND`), and switching off. The development compose file has
  the variables commented out; nothing is switched on. TODO SRV-019 (staging run before any production use).

### Studio pin: macOS build fix (2026-11-02)

- `studio.json` pins studio `bae25eb` (before: `0055a30`; the merge commit of studio #89): the frontend component
  `automation/TestStatus.tsx` is renamed to `WorkflowTestStatus.tsx`, so the build works on case-insensitive file
  systems (macOS), plus the case-clash CI check. Component pins unchanged (runtime `a42b672`, api `fb7f438`,
  sdk `dbbc7e5`, orkexa `3467940`).

### Live run chat and steering (LRC-1, 2026-11-01)

- New acceptance test against the built image: the live run chat routes (`/api/runs/{id}/chat`, messages, the
  event stream) answer through the proxy chain, refuse a target that is not a team leader (404), keep other tenants
  out (404) and close with the run. Delivery to an orchestrator in the worker is covered by the runtime's PostgreSQL
  tests: the OpenAI-compatible model stub cannot answer orchestrator decisions (structured output with reasoning
  effort).
- RUNBOOK: how the live run chat works on a server, its limits and environment variables.
- `studio.json` pins studio `0055a30` (before: `b8c6d48`; the merge commit of studio #77, LRC-1 on top of Bedrock):
  runtime `a42b672`, api `fb7f438`, sdk `dbbc7e5`, orkexa `3467940`.

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
