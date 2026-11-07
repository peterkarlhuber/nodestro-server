# Nodestro server runbook

How to install, configure, operate, back up and upgrade a Nodestro server. The development stack in
`compose/compose.yaml` shows every part working together on one Linux machine; a production installation uses the
same image and the same settings with its own PostgreSQL, identity provider, TLS proxy and sandbox host.

## What runs where

| Part | What it does | Notes |
| --- | --- | --- |
| `nodestro-server api` | The studio (web interface and API) with logins | Stateless; several can run behind the proxy |
| `nodestro-server worker` | Executes queued runs, reaps runs of dead workers, fires schedules, cleans up | One or more |
| `nodestro-server migrate` | Applies database migrations, then exits | Before API and workers start |
| PostgreSQL 17 (with pgvector, recommended) | All data of all tenants | Back it up (see below); the image's `pg_dump`/`pg_restore` are version 17. pgvector: see [Semantic knowledge search](#semantic-knowledge-search-and-local-models) |
| OpenID Connect provider | Logins (Keycloak, Entra ID, Okta, Dex, …) | The server never sees passwords |
| Sandbox Docker daemon | Runs tool code in containers | Not the host's daemon (see below) |
| TLS reverse proxy | https for the studio | nginx, Caddy, Traefik, a load balancer |

The API and the worker start only when the configuration is complete, the database schema is current and the
sandbox daemon is reachable. Otherwise they stop with one sentence that names the problem.

## Install

1. Build the image (or take it from your registry): `scripts/build-image.sh
   registry.example.com/nodestro-server:<version>`. `studio.json` names the studio commit; it pins every
   component by full commit SHA. The component repositories are public; a token in `NODESTRO_READ` is optional and
   reaches the build only as a BuildKit secret.
2. Create the database and two roles (see [Database roles](#database-roles)): `nodestro_owner` owns the tables and
   runs `migrate`, backups and restores; `nodestro_app` is the API's and the workers' role. As a superuser, connected
   to the new database: `psql -d nodestro -v owner_password=… -v app_password=… -f compose/postgres/roles.sql` after
   `CREATE DATABASE nodestro;` (or the statements in [Database roles](#database-roles) by hand). Where the server
   has pgvector, `roles.sql` also installs it (`CREATE EXTENSION IF NOT EXISTS vector`).
3. Register a client at your identity provider: confidential client, authorization code flow with PKCE (S256),
   redirect URI `https://<studio host>/api/auth/callback`, scopes `openid email profile`.
4. Generate the server's secret key once and keep it with your other secrets: `openssl rand -base64 32`.
   It encrypts the tenants' provider keys. Without it they cannot be read; there is no rotation yet.
5. Prepare the sandbox host (see [The sandbox daemon](#the-sandbox-daemon)).
6. Run `nodestro-server migrate` with `NODESTRO_DATABASE_MIGRATION_URL` (the owner) and `NODESTRO_DATABASE_URL`
   (the runtime role) set, then start the API and the workers (only `NODESTRO_DATABASE_URL`), then the proxy.
7. Create the first tenant and its owner:
   `nodestro-server create-tenant acme "Acme Inc."` and `nodestro-server setup-link acme`. The link is valid for
   24 hours and once; whoever logs in with it becomes the tenant's first owner.
8. Add everyone else (see [Members](#members)): each person logs in once (they are told that they have no access
   yet), then an operator grants a role, for example `nodestro-server set-role acme bob@example.com editor` (on a
   terminal: the command shows the user and their identity and asks for their user id) or
   `nodestro-server set-role acme u_… editor`.

## Members

Owners and administrators manage the members of their tenant in the studio (Settings → Members: change a role,
remove a member; only an owner gives, takes or changes the owner role). Operators use these commands as well, for
example to add a person or to manage a tenant without an administrator. `USER` is a user id
(`u_…`) or the person's subject at the configured identity provider. An e-mail address (compared
case-insensitively) only looks the person up: it is the latest claim of the identity provider, so it never names a
user by itself. The command prints the matching user with their provider, subject and name and goes on only when you
type that user id; without a terminal (scripts, `docker compose run -T`) it stops with `identity.user_confirm` and
names the user id to use. The person must have logged in once, so that the server knows them.

| Command | What it does |
| --- | --- |
| `nodestro-server members TENANT` | Lists the members with user id, role, e-mail address, name and subject |
| `nodestro-server set-role TENANT USER ROLE` | Adds the person to the tenant or changes their role (`owner`, `admin`, `editor`, `operator`, `viewer`); takes effect with their next request |
| `nodestro-server remove-member TENANT USER` | Removes the person from the tenant and ends their sessions there |
| `nodestro-server revoke-sessions USER` | Ends every session of the person in every tenant (logs them out everywhere; memberships stay) |
| `nodestro-server suspend-tenant TENANT` | Closes the tenant at once: its sessions, logins, switches to it and setup links are refused (`identity.tenant_suspended`), workers neither start nor continue its runs and fire none of its schedules. Nothing is deleted |
| `nodestro-server resume-tenant TENANT` | Opens a suspended tenant again; sessions that did not expire meanwhile work again, interrupted runs can be continued |

Errors: `identity.user_unknown` (nobody with that name has logged in yet), `identity.user_confirm` (an e-mail address
that was not confirmed; use the user id it names), `identity.user_ambiguous` (the e-mail address names several users,
each listed with their identity; use the user id), `identity.tenant_unknown`, `identity.not_a_member` and
`identity.last_owner` (a tenant keeps at least one owner).

## Configuration

Every setting comes from the environment. A `…_FILE` variable names a file holding the value instead (container
secrets); giving both forms is refused. Nothing has a default that weakens the server.

| Variable | Meaning |
| --- | --- |
| `NODESTRO_PROFILE` | `server` (set in the image) |
| `NODESTRO_DATABASE_URL` / `_FILE` | PostgreSQL connection (`host=… port=… user=… dbname=… password=…` or a URL) of the runtime role (`nodestro_app`) |
| `NODESTRO_DATABASE_MIGRATION_URL` / `_FILE` | The owner role's connection (`nodestro_owner`), for `migrate`, `backup`, `db grant-runtime-role` and restores only; never give it to the API or the workers. Unset: those commands use `NODESTRO_DATABASE_URL` (one role for everything, as before) |
| `NODESTRO_PUBLIC_ORIGIN` | `https://studio.example.com` as browsers see it (`http://` only for localhost) |
| `NODESTRO_OIDC_ISSUER` | The provider's issuer URL (https; `http://` only for localhost) |
| `NODESTRO_OIDC_CLIENT_ID` | The client registered for the studio |
| `NODESTRO_OIDC_CLIENT_SECRET` / `_FILE` | Its secret |
| `NODESTRO_SECRET_KEY` / `_FILE` | At least 32 random bytes, base64 |
| `NODESTRO_MODEL_ENDPOINTS` | Comma-separated origins of self-hosted model endpoints tenants may use (Ollama, vLLM, …). Empty: none |
| `NODESTRO_BEDROCK_TENANT_ROLES` / `_FILE` | Amazon Bedrock: the IAM role each tenant uses, as JSON `{"<tenant_id>": {"role_arn": "…", "external_id": "…"}}`. Unset: no tenant can use Bedrock. See [Amazon Bedrock for tenants](#amazon-bedrock-for-tenants) |
| `NODESTRO_BEDROCK_DATA_RESIDENCY` | `eu_only`: every tenant's Bedrock calls stay in EU regions; a tenant cannot relax it. Unset: each tenant chooses |
| `NODESTRO_BEDROCK_ALLOWED_REGIONS` | Comma-separated AWS regions tenants may use for Bedrock (e.g. `eu-central-1,eu-west-1`). Unset: no extra limit |
| `NODESTRO_MAX_RUN_BUDGET_USD` | The highest budget a person may set for one run when it waits for a budget decision (all tenants; a tenant's own `max_run_budget_usd` can only be lower). Empty: no operator maximum. A raise never changes a stored workflow or another run |
| `NODESTRO_WORKER_LEASE_SECONDS` | How long a run stays a worker's without a heartbeat (default 60) |
| `NODESTRO_WORKER_POLL_SECONDS`, `NODESTRO_WORKER_REAP_SECONDS` | Worker intervals (defaults 1 and 15) |
| `NODESTRO_WORKER_CLEANUP_SECONDS` | How often the scheduler leader cleans up (default 600): it deletes expired sessions and abandoned login starts, finished jobs after 7 days and run events after 2 days (the runs themselves stay) |
| `NODESTRO_TENANT_IDLE_MINUTES` | Minutes after which an API process closes a tenant's context that no request uses and that has no background work (default 30; `0` keeps contexts open). The next request opens it again |
| `NODESTRO_SERVER_EXPORT_TENANT_QUOTA_BYTES` | The most bytes of export packages one tenant keeps on the server (default 8 GiB). A build beyond it is refused with `export.server_quota`; members free space by deleting exports |
| `NODESTRO_DATABASE_POOL_SIZE` | Database connections per API or worker process (default 8) |
| `NODESTRO_DATABASE_STATEMENT_TIMEOUT` | Longest time one SQL statement may run, in seconds (default 30; 0: no limit). Migrations have no limit |
| `NODESTRO_DATABASE_IDLE_IN_TRANSACTION_TIMEOUT` | Longest time a transaction may stay idle, in seconds (default 300) |
| `NODESTRO_RUN_THREADS` | Threads for agents and orchestrator decisions of one tenant in one process (default 32); an agent beyond the limit waits for a thread |
| `NODESTRO_DATA_DIR` | Files of the tenants (`/var/lib/nodestro` in the image): a shared volume for API and workers |
| `DOCKER_HOST`, `DOCKER_TLS_VERIFY`, `DOCKER_CERT_PATH` | The sandbox daemon (TLS with client certificates) |
| `NODESTRO_BEHIND_PROXY` | `1`: the API runs behind a reverse proxy, so `FORWARDED_ALLOW_IPS` must be set. See [Client addresses behind a reverse proxy](#client-addresses-behind-a-reverse-proxy) |
| `FORWARDED_ALLOW_IPS` | uvicorn's list of proxy addresses (comma-separated IP addresses or networks) whose `X-Forwarded-For` the API trusts; default `127.0.0.1`. Never `*` where others can reach the API port |
| `NODESTRO_REQUIRE_CLIENT_ADDRESS` | `1`: `check` and `api` refuse to start (`proxy.client_address_unknown`) when `NODESTRO_BEHIND_PROXY=1` and `FORWARDED_ALLOW_IPS` is not set, instead of only warning |
| `NODESTRO_BUILD_CA_FILE`, `SSL_CERT_FILE`, `AWS_CA_BUNDLE` | Only behind a TLS-inspecting proxy: its certificate bundle. The AWS SDK (Bedrock, STS) ignores `SSL_CERT_FILE` and reads only `AWS_CA_BUNDLE`; `compose/extra-ca.yaml` sets all three |

`nodestro-server check` validates these settings, the database (role and schema), the container runtime and the
identity provider's discovery document (`NODESTRO_OIDC_ISSUER`), and exits with 0 when the server is ready. An
incomplete or unsafe configuration is refused with `profile.invalid`, listing every problem at once; secret values are
never printed.

The server never uses provider keys from its own environment for tenants: each tenant enters its own keys, which
are stored encrypted (AES-256-GCM, a key per tenant derived from `NODESTRO_SECRET_KEY`). Amazon Bedrock has no key:
the operator assigns each tenant an IAM role (next section).

PostgreSQL's `max_connections` must cover every process: (`NODESTRO_DATABASE_POOL_SIZE` + 1 connection for locks)
× the number of API and worker processes, plus a few for operator commands such as `migrate` and `backup`. With the
defaults, one API and two workers need up to 27 connections. With `NODESTRO_AXENTRA=on` the numbers stay the same:
Axentra uses the process's pool and opens none of its own (one pool per process; nodestro-runtime `docs/AXENTRA.md`). Every connection is checked before it is used, so a
connection the database dropped (a restart, a failover, a proxy's idle timeout) is replaced without restarting the
API or the workers.

## Axentra platform services (optional, off by default)

The server can use Axentra, the platform's generic SaaS backend library, in the same PostgreSQL database (tables
`axentra_*` next to `nodestro_*`). Nothing changes for users: login, sessions, API keys, tenant ids and the API stay
as they are. Details, rollback and what stays Nodestro's: `docs/AXENTRA.md` in nodestro-runtime. **No switch is
approved for production yet**; use them on a staging copy first.

| Variable | Meaning |
| --- | --- |
| `NODESTRO_AXENTRA` | `on`: open Axentra (default `off`). The image always has the package (Python 3.13) |
| `NODESTRO_AXENTRA_KEYRING` / `_FILE` | Axentra keyring `kid:base64key[,kid2:…]` (first key encrypts); required with `on`. Keep it like `NODESTRO_SECRET_KEY` |
| `NODESTRO_AXENTRA_ALLOW_SUPERUSER` | `1` allows a superuser or `BYPASSRLS` database role (development only; Axentra's row-level security is then no defense in depth) |
| `NODESTRO_SECRETS_FORMAT` | `axs1`: new tenant secrets use the keyring (rotation); default `v1` |
| `NODESTRO_AXENTRA_AUDIT`, `NODESTRO_AXENTRA_USAGE` | `1`: mirror the approval/MCP audit trail and the AI usage ledger into Axentra, in the same transaction |
| `NODESTRO_AXENTRA_RUN_USAGE` | `1`: the worker also settles the usage of finished runs into Axentra's meters, once per run (needs `NODESTRO_AXENTRA_USAGE=1`); no limit is enforced |
| `NODESTRO_AXENTRA_NOTIFY` | `1`: failed runs, pending tool approvals and budget decisions go to the members' in-app inbox (`/api/notifications`); never e-mail. Notifications need the identity backfill (linked users) |
| `NODESTRO_AXENTRA_CONFIG` | Optional Axentra TOML file for Axentra's own knobs |
| `NODESTRO_IDENTITY_BACKEND` | `nodestro` (default), `mirror` (Nodestro answers, identity writes also go to Axentra in the same transaction) or `axentra` (Axentra answers, both are written). Needs `on` |
| `NODESTRO_FILES_BACKEND` | `volume` (default) or `axentra`: input file bytes in Axentra's storage (`[storage]` in `NODESTRO_AXENTRA_CONFIG`: local directory or S3). Needs `on` |
| `NODESTRO_FILES_SOURCE_REMOVAL`, `NODESTRO_FILES_SOURCE_RETENTION_DAYS` | `1` allows `files remove-source` (default `0`); days a migrated volume file stays as the fallback (default 30) |

Switching on:

1. Take a backup, then `nodestro-server migrate --backup-dir DIR` (applies Nodestro's and Axentra's migrations
   after one `pg_dump`). `nodestro-server axentra status` shows the switches and pending migrations; `check`, `api`
   and `worker` refuse to start while either schema is behind.
2. The database roles of [Database roles](#database-roles): the API and the workers connect as a role without
   `SUPERUSER` and `BYPASSRLS` that owns no tables, or `check`, `api` and `worker` stop with `storage.role_unsafe`.
   `NODESTRO_AXENTRA_ALLOW_SUPERUSER=1` lifts this for a throwaway development database only. The development
   compose file uses separate roles already.
3. Key rotation: put the new key first in the keyring, restart, run `nodestro-server secrets reencrypt --dry-run`, then
   `secrets reencrypt` (resumable; an unreadable value is reported and never overwritten, exit code 2). Without
   `--tenant` it also re-encrypts Axentra's own encrypted columns (its `axentra` section; `pending` and `failed` count
   both, `nodestro_pending`/`nodestro_failed` Nodestro's part alone). Remove an old key only after `pending: 0` and
   `failed: []`: the start refuses a keyring that lacks a key id still used by Nodestro's or Axentra's values, or
   whose key under a known id does not decrypt the stored values. Keep `NODESTRO_SECRET_KEY` while v1 values remain.
4. Mirrors: after switching `NODESTRO_AXENTRA_AUDIT` / `_USAGE` on, `nodestro-server axentra reconcile --dry-run`
   counts what is missing (older records, a failed mirror) and `axentra reconcile` writes it (idempotent).
5. Identity: `nodestro-server axentra backfill-identity --dry-run`, then without `--dry-run` (idempotent, one
   transaction per record group); `axentra reconcile-identity` must print `"ok": true`. Then
   `NODESTRO_IDENTITY_BACKEND=mirror`, restart; later `axentra`, restart (refused with `identity.backfill_required`
   while records are missing on one side). Sessions are copied with their hash, so nobody logs in again. Accounts of
   different identity providers are never merged by e-mail address. Back: `axentra` -> `mirror` -> `nodestro`, a
   restart each; after time in `nodestro` mode run the backfill again before switching forward. In `axentra` mode
   Axentra also runs the login (same routes and cookies) and decides permissions from its role definitions, which
   every start registers as a versioned revision (an older image never undoes a newer one; a start with a
   conflicting revision is refused with `identity.access_conflict`). Login starts are rate-limited per client
   address: behind the reverse proxy set `FORWARDED_ALLOW_IPS` to the proxy's address so the server sees client
   addresses. A tenant suspended in Axentra directly is closed too; resume it with `resume-tenant`.
6. Input files: set `[storage]` in `NODESTRO_AXENTRA_CONFIG` (`backend = "local"` with an absolute `local_path` that
   API and workers share, or `backend = "s3"` with the bucket) and `NODESTRO_FILES_BACKEND=axentra`; `check` must be
   `ready`; restart. New uploads go to Axentra, older files are read from the data volume. Then
   `nodestro-server files migrate --dry-run`, `files migrate` (resumable, idempotent, SHA-256 checked, never deletes
   the volume file; exit code 2 when a file failed) and `files verify` (must print `"ok": true`; `pending` counts
   files not copied yet). Leftovers older than an hour make `verify` print `"ok": false` (exit code 2): `orphans`
   (stored objects without a reference, e.g. from an interrupted copy) and `unreferenced` (references no input file
   uses, e.g. a file deleted while the backend was `volume`). `files cleanup --dry-run` lists them, `files cleanup`
   deletes them in Axentra (never on the volume). After the fallback period:
   `NODESTRO_FILES_SOURCE_REMOVAL=1 nodestro-server files remove-source --dry-run`, then without `--dry-run` (only
   verified files whose fallback period has passed). Keep the data volume shared between API and workers until then.
   Back: `files export-volume` (copies the files that exist only in Axentra back to the volume), then
   `NODESTRO_FILES_BACKEND=volume` and restart. Files deleted while the backend is `volume` are deleted only on the
   volume: after switching forward again, run `files verify` and `files cleanup` so their content leaves Axentra too.
   The volume's catalog is locked across processes, so `remove-source` and `export-volume` may run while the API and
   the workers do. Details: `docs/AXENTRA.md` in nodestro-runtime, section "Files".

Switching off again needs no data change (Axentra's tables stay and are not read), except that values written in
the `axs1` format need the keyring. `check`, `api` and `worker` refuse to start (`profile.invalid`) with
`NODESTRO_AXENTRA=off` while `axs1` values exist, and with a keyring that lacks a key id still in use. The way back:
keep `on` and the keyring, set `NODESTRO_SECRETS_FORMAT=v1`, restart, run `nodestro-server secrets reencrypt` (it
moves the `axs1` values back to v1) until it reports `pending: 0` and `failed: []`, then switch off. Or restore the
backup. `nodestro-server axentra status` shows the stored secrets by format and whether the configuration can read
them.

## Database roles

The server uses two database roles, and the superuser only to create them:

| Role | Used by | Attributes |
| --- | --- | --- |
| `nodestro_owner` | `migrate`, `backup`, `db grant-runtime-role`, restores (`NODESTRO_DATABASE_MIGRATION_URL`) | `LOGIN NOSUPERUSER BYPASSRLS`; owns the tables (Nodestro's and Axentra's) and may create objects in the schema |
| `nodestro_app` | `api`, `worker`, `check` and the other commands (`NODESTRO_DATABASE_URL`) | `LOGIN NOSUPERUSER NOBYPASSRLS`; owns nothing; reads and writes rows, no DDL |

Why: row-level security does not apply to superusers and roles with `BYPASSRLS`, and a table's owner can switch it off.
Axentra's tables force row-level security per tenant; it is defense in depth only when the server's role is none of
these. The owner needs `BYPASSRLS` for one reason: `pg_dump` must read every row of those tables (without it the
backup stops with an error rather than writing an incomplete dump).

`compose/postgres/roles.sql` creates or updates both roles (idempotent; run it as a superuser in the server's
database with the psql variables `owner_password` and `app_password`). By hand:

```sql
CREATE ROLE nodestro_owner LOGIN NOSUPERUSER BYPASSRLS PASSWORD '…';
CREATE ROLE nodestro_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '…';
GRANT CONNECT, TEMPORARY ON DATABASE nodestro TO nodestro_owner, nodestro_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO nodestro_owner;
GRANT USAGE ON SCHEMA public TO nodestro_app;
```

With `NODESTRO_DATABASE_SCHEMA`, create that schema `AUTHORIZATION nodestro_owner` instead of granting on `public`.

Optional, as the superuser: `CREATE EXTENSION IF NOT EXISTS vector;` where pgvector is available (`roles.sql` does it
by itself). pgvector is not a trusted extension, so neither role can install it.

`nodestro-server migrate` connects as the owner. Before it changes anything it checks the runtime role (the user of
`NODESTRO_DATABASE_URL`) and refuses with `storage.role_unsafe` when it is a superuser, has `BYPASSRLS` or owns
tables; afterwards it grants the runtime role `SELECT, INSERT, UPDATE, DELETE` on every table, `USAGE, SELECT` on the
sequences and `EXECUTE` on the functions of the schema, now and for later tables (default privileges). It cannot
write the schema-version tables. Two commands for operators (both as the owner):

| Command | What it does |
| --- | --- |
| `nodestro-server db roles` | Prints both roles as JSON: superuser, `BYPASSRLS`, owned tables, whether the owner can back up. Exit code 3 when the runtime role is not restricted |
| `nodestro-server db grant-runtime-role [ROLE]` | Grants the runtime role (default: the user of `NODESTRO_DATABASE_URL`) its privileges again, for example after a restore with `--no-acl`. Refused (`storage.role_unsafe`) for an unsafe role; needs `NODESTRO_DATABASE_MIGRATION_URL` |

In the development stack: `docker compose -f compose/compose.yaml run --rm --no-deps migrate db roles`.

Moving an existing installation (one role that owns the tables, or a superuser) to separate roles:

1. Take a backup (`nodestro-server backup`).
2. As a superuser, run `compose/postgres/roles.sql` in the server's database. It creates the roles and gives the
   owner role the tables, views, sequences, functions and types of the `public` schema that the connecting role owns
   (nothing is dropped or rewritten). When the tables belong to another role than the one connecting, transfer them
   instead with `REASSIGN OWNED BY <old owner> TO nodestro_owner;` (every schema of the database, and the database
   itself; not possible for the cluster's bootstrap superuser, which `roles.sql` covers).
3. Set `NODESTRO_DATABASE_MIGRATION_URL` (owner) for `migrate` and `backup`, `NODESTRO_DATABASE_URL` (runtime role)
   everywhere, and remove `NODESTRO_AXENTRA_ALLOW_SUPERUSER`.
4. Run `nodestro-server migrate` (grants the runtime role), then `nodestro-server db roles` (exit code 0), then start
   the API and the workers.

The development stack does this by itself: its `db-roles` service runs `roles.sql` on every start, and
`scripts/dev-secrets.py` rewrites a `database_url` that still names the superuser `nodestro`.

**Axentra and the table owner (MUP-ONA A6).** A role that owns tables protected by row-level security can switch
row-level security off, so it must not be the role the API and the workers connect as:

- **This server:** with `NODESTRO_AXENTRA=on`, Nodestro checks the runtime role itself before Axentra starts, in every
  environment: a superuser, a `BYPASSRLS` role or a role that owns tables stops `check`, `api` and `worker`
  (`storage.role_unsafe` / `axentra.unavailable`) unless `NODESTRO_AXENTRA_ALLOW_SUPERUSER=1` (development only). It
  passes Axentra `allow_superuser` and `allow_table_owner` from that one variable; `[database]` values in
  `NODESTRO_AXENTRA_CONFIG` and `AXENTRA__*` variables do not change them. Axentra runs as `production` when
  `NODESTRO_PUBLIC_ORIGIN` is https. Nothing changes for a server with the roles above (`nodestro_owner` migrates,
  `nodestro_app` connects).
- **Axentra on its own** (its own configuration, not this server): `database.allow_table_owner` is unset by default,
  which means `false` in production (`environment = "production"`) and `true` in development and test. In production
  `Axentra.start()` then refuses an application role that owns the tables (`configuration_error`, "refusing to start:
  the database role owns the tables protected by row-level security …"). Use a separate owner role for migrations
  (`database.migration_url_ref`, `axentra migrate --grant-runtime-role <role>`) and connect as a runtime role that owns
  nothing, or accept the risk explicitly with `allow_table_owner = true` (`AXENTRA__DATABASE__ALLOW_TABLE_OWNER=true`),
  which starts with a warning. `allow_table_owner = false` refuses an owner role in every environment. This is a
  breaking change for production installations of Axentra that connect as the owner; it takes effect with the
  Axentra version that contains MUP-ONA A6.

## Semantic knowledge search and local models

Knowledge search has three modes (nodestro-runtime `docs/local-models.md`): full text (the default, needs nothing),
`vector` and `hybrid` (embeddings, once a person built a knowledge base's semantic index). The vectors are stored in
the table `nodestro_chunk_vectors` (migration `0010`, tenant-scoped like every other table) as `real[]`.

- **pgvector** (recommended): PostgreSQL ranks the vectors. The development stack uses
  `pgvector/pgvector:0.8.7-pg17`, the official `postgres:17` image plus the extension, pinned by digest in
  `compose/compose.yaml`; `db-roles` installs the extension as the superuser. For your own PostgreSQL 17, install
  the pgvector package of your distribution or provider and run `CREATE EXTENSION IF NOT EXISTS vector;` as a
  superuser in the server's database (or `roles.sql` again). Migration `0010` tries the same, but as the owner role it
  usually may not and goes on without it.
- **Without pgvector**: semantic search still works; the runtime ranks the same rows (slower for large knowledge
  bases). Installing pgvector later needs no reindex: the stored vectors are used as they are.
- **Reindex jobs:** building or rebuilding a semantic index is a `reindex` job of the job queue that a worker runs
  with a lease, like runs. A restarted API process or worker loses nothing: another worker continues where the job
  stopped, and every API process shows its progress.

Switching an existing compose installation from `postgres:17` to the pgvector image keeps the data volume: both are
PostgreSQL 17 with the same data format. Rolling back to `postgres:17` also starts; the installed extension is then
unused. `ALTER EXTENSION vector UPDATE;` (superuser) after a new pgvector image.

Backups contain the extension's `CREATE EXTENSION` entry, which the owner role may neither drop nor create. Restores
leave extensions out (see [Backup and restore](#backup-and-restore)); a superuser installs them.

The server runs **no local model server** of its own. Tenants use models on self-hosted endpoints (Ollama, vLLM, …)
that the operator runs and lists in `NODESTRO_MODEL_ENDPOINTS` (for example `http://ollama.internal:11434`); the
embedding model of semantic search (default `qwen3-embedding:0.6b`) runs on such an endpoint too. Run Ollama on a host
with enough memory (GPU recommended), on a network the workers and the API reach and the internet does not.

**Keep `NODESTRO_MODEL_ENDPOINTS` narrow (MUP-ONA A7, PS-7).** Tenant admins choose the base URL of an
OpenAI-compatible, Ollama or vLLM endpoint themselves. The server sends those requests from inside its network, so the
only protection against a tenant reaching internal services through it (server-side request forgery) is this list:
an endpoint is used only when its origin (`scheme://host:port`, compared exactly; no wildcards, no paths) is listed,
checked again on every use, and redirects are not followed. There is no second, address-based check for these
endpoints. Therefore:

- list only the origins of model servers you run for tenants, each with its port (`http://ollama.internal:11434`,
  not a whole host or network); leave the variable empty when tenants use no self-hosted endpoint;
- never list an origin that serves anything else: the database, the Docker or sandbox daemon, the metrics endpoint,
  a cloud metadata service (`169.254.169.254`), an admin interface or a proxy that forwards elsewhere;
- prefer `https` and a name that resolves only to that model server; review the list when model servers move, and
  remove origins no tenant uses;
- put the model servers on a network segment that reaches nothing else the tenants must not use.

This is an accepted risk of the operator's configuration (PS-7): a list kept too wide lets tenants send requests to
whatever it names. The public provider APIs (Anthropic, OpenAI, Gemini, Bedrock) are not affected; their addresses are
fixed.

## Amazon Bedrock for tenants

Tenants **never** use the server's own (ambient) AWS credentials: not its environment, not `~/.aws`, not an
instance or pod role. Bedrock is off for every tenant (`provider.bedrock_not_available`) until the operator assigns
the tenant an IAM role. The tenant sees only that a role is assigned, never its ARN or the external ID, and cannot
choose a role itself. Nodestro never stores AWS access keys.

**Assign roles.** `NODESTRO_BEDROCK_TENANT_ROLES` (or `NODESTRO_BEDROCK_TENANT_ROLES_FILE`, a file with the same
JSON; giving both is refused) maps tenant IDs to roles:

```json
{
  "<tenant_id>": {"role_arn": "arn:aws:iam::111122223333:role/nodestro-tenant-acme", "external_id": "<random, per tenant>"}
}
```

Use one role and one random external ID per tenant. The server assumes the tenant's role with STS (`ExternalId`,
session name `nodestro-<tenant>`, sessions of 1800 seconds that botocore refreshes 15 minutes before they expire,
the regional STS endpoint; the role's maximum session duration must allow 1800 seconds) in a session
of that tenant alone, and gives the tenant's agents only that session. `NODESTRO_BEDROCK_DATA_RESIDENCY=eu_only` forces EU-only processing for all
tenants (EU regions and EU cross-region inference profiles only). `NODESTRO_BEDROCK_ALLOWED_REGIONS` limits the
regions further. `nodestro-server check` validates all three (`nodestro_runtime.bedrock.BedrockOperatorConfig`).

**The server's base identity** (environment, IRSA/web identity or an instance role) needs only `sts:AssumeRole` on
the tenant roles, nothing for Bedrock itself:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "sts:AssumeRole",
    "Resource": ["arn:aws:iam::111122223333:role/nodestro-tenant-*"]
  }]
}
```

**Trust policy of each tenant role**: only the server's base identity, only with the tenant's external ID:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::444455556666:role/nodestro-server"},
    "Action": "sts:AssumeRole",
    "Condition": {"StringEquals": {"sts:ExternalId": "<the tenant's external_id>"}}
  }]
}
```

**Permissions of each tenant role**: as little as possible. Name the models and inference profiles the tenant may use;
add `bedrock:GetGuardrail` (on the guardrail's ARN) only if the tenant uses a guardrail:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:eu-central-1:111122223333:inference-profile/eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "bedrock:GetInferenceProfile",
      "Resource": "arn:aws:bedrock:eu-central-1:111122223333:inference-profile/*"
    }
  ]
}
```

A cross-region inference profile also needs the foundation model in every region it routes to (hence the `*`
region above). The connection check in the studio (Settings, Amazon Bedrock, verify) calls only free read operations
and never invokes a model: `sts:GetCallerIdentity` (allowed for every identity, no policy needed) and
`bedrock:ListFoundationModels`, or `bedrock:GetInferenceProfile` / `bedrock:GetFoundationModel` when a model is given.
Add to the tenant role:

```json
{
  "Effect": "Allow",
  "Action": ["bedrock:ListFoundationModels", "bedrock:GetFoundationModel"],
  "Resource": "*"
}
```

**Keep data in the EU** with a service control policy in addition to `eu_only`, so that no credential of the
account can call Bedrock outside the EU:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "BedrockOnlyInTheEU",
    "Effect": "Deny",
    "Action": "bedrock:*",
    "Resource": "*",
    "Condition": {"StringNotLike": {"aws:RequestedRegion": ["eu-*"]}}
  }]
}
```

**Instance metadata (IMDS).** On EC2 with an instance role, require IMDSv2 with a hop limit of 1
(`aws ec2 modify-instance-metadata-options --http-tokens required --http-put-response-hop-limit 1`), so containers
cannot fetch the instance role's credentials; or block `169.254.169.254` in the sandbox daemon's networks, because
tool environment builds have network access. With the hop limit 1, the server itself must get its base credentials
another way (environment, IRSA/web identity, or a host network).

**Egress.** For every region tenants may use, allow `bedrock-runtime.<region>.amazonaws.com` (model calls),
`bedrock.<region>.amazonaws.com` (control plane: inference profiles, models) and `sts.<region>.amazonaws.com` (role
assumption) from the API and the workers. Cross-region inference profiles are called on the source region's endpoint,
so no further hosts are needed. Proxies: the AWS SDK honours `HTTPS_PROXY`/`NO_PROXY`, but for a TLS-inspecting
proxy it needs `AWS_CA_BUNDLE` (it ignores `SSL_CERT_FILE`); `compose/extra-ca.yaml` sets it.

**Model invocation logging** in Bedrock stores the full prompts and responses in your S3 bucket or CloudWatch. It is
off by default; switch it on only knowingly, and treat its destination like tenant data.

## TLS reverse proxy

The API listens on plain http; put it behind a proxy that terminates TLS and forwards to it. The session cookie is
`__Host-` prefixed and `Secure`, so the studio works only over https (and on localhost for development).

```nginx
# http block (for example /etc/nginx/conf.d/nodestro.conf): the request line and the referrer are logged
# without their query string, so setup links (?setup=) and sign-in codes (?code=, &state=) never reach the
# proxy's access log. nginx's predefined "combined" format logs the full request line: do not use it here.
map $request_uri $nodestro_log_path {
    "~^(?<path>[^?]*)" $path;
}
map $http_referer $nodestro_log_referer {
    "~^(?<ref>[^?]*)" $ref;
}
log_format nodestro '$remote_addr [$time_local] "$request_method $nodestro_log_path $server_protocol" '
                    '$status $body_bytes_sent $request_time "$nodestro_log_referer" "$http_user_agent"';

server {
    listen 443 ssl;
    server_name studio.example.com;
    ssl_certificate     /etc/ssl/studio.pem;
    ssl_certificate_key /etc/ssl/studio.key;
    access_log /var/log/nginx/studio.access.log nodestro;
    error_log  /var/log/nginx/studio.error.log warn;
    client_max_body_size 100m;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_buffering off;            # run events are streamed
        proxy_read_timeout 1h;
    }
    # nginx's error messages quote the full request line and the upstream URL, query included (for example
    # when the API is unreachable). Where setup links and sign-in callbacks arrive, only critical errors are
    # logged.
    location /api/auth/ {
        error_log /var/log/nginx/studio.error.log crit;
        proxy_pass http://127.0.0.1:8080;
    }
    location = /api/mcp/oauth/callback {
        error_log /var/log/nginx/studio.error.log crit;
        proxy_pass http://127.0.0.1:8080;
    }
}
```

The proxy's logs must not contain the query strings of `/api/auth/` and `/api/mcp/oauth/callback`: a setup link is
valid for 24 hours and makes whoever completes the login the tenant's owner. The server redacts these values in its
own access log (see [Security notes](#security-notes)), but that does not cover the proxy, which logs the request one
hop earlier. Other proxies need the same: Caddy's access log (`format filter`, a `query` filter on `request>uri` that
deletes `setup`, `code` and `state`), Traefik's access log (`fields.names.RequestPath: redact`), a load balancer's
request log. `scripts/test_runbook_proxy.py` checks this example (and, with Docker, runs nginx with it).

Browser security headers (`Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`,
`Referrer-Policy`, and `Strict-Transport-Security` when `NODESTRO_PUBLIC_ORIGIN` is https) are set by the server
itself from the nodestro-api version with API2-02 on; do not add them in the proxy as well, since a second header with
a different value can break the studio. With an older pinned studio, add at least
`add_header Strict-Transport-Security "max-age=31536000" always;` to the `server` block.

Bind the API to `127.0.0.1` or a private network (`nodestro-server api --host 127.0.0.1`); never publish port 8080.

The server limits login starts per API process (see "Login rate limit" below); a rate limit for `/api/auth/` in the proxy is still advisable
(for nginx: a `limit_req_zone` in the `http` block and `limit_req` in the `location /api/auth/` above). The server serves the studio gzip-compressed, with long-lived immutable caching for the
content-hashed files under `/assets` and `no-cache` for `index.html`, so the proxy need not compress it.

**Login rate limit.** Each API process lets one client address start at most 60 logins per minute
(`NODESTRO_LOGIN_STARTS_PER_MINUTE`, default `60`; `0` turns the limit off). Further starts get
`429 identity.rate_limited` until the minute has passed. The limit counts per process, so with N API processes an
address can start up to N × the limit. Keep the rate limit on the reverse proxy as the first line of defense.

**Client addresses behind the proxy.** `nodestro-server api` runs uvicorn with proxy headers on, but uvicorn trusts
`X-Forwarded-For` only from the addresses in `FORWARDED_ALLOW_IPS` (default `127.0.0.1`). When the proxy runs
in another container or host, set `FORWARDED_ALLOW_IPS` to the proxy's address (never `*` on a network others can
reach). Otherwise every request seems to come from the proxy, and the login rate limit applies to all users
together. Set `NODESTRO_BEHIND_PROXY=1` as well, so the server reports a missing `FORWARDED_ALLOW_IPS`; details and
the examples for nginx, Caddy and Traefik are in the next section.

## Client addresses behind a reverse proxy

The API limits some requests per client address: login starts (`NODESTRO_LOGIN_STARTS_PER_MINUTE`) and failed API
keys of published workflow APIs. Behind a reverse proxy the API sees the proxy's address unless the proxy passes
the client's address in `X-Forwarded-For` **and** the API trusts that header from the proxy. Then one client that
uses up its budget would lock out every other client.

| Variable | Set it to |
| --- | --- |
| `NODESTRO_BEHIND_PROXY` | `1` whenever a reverse proxy or load balancer forwards to the API |
| `FORWARDED_ALLOW_IPS` | the address(es) from which the proxy connects to the API, comma-separated (IP addresses or networks such as `10.0.5.0/28`); only those may set the client address. Default `127.0.0.1` (a proxy on the same host). Never `*` where other hosts or containers can reach the API port: anyone could then claim any address |
| `NODESTRO_REQUIRE_CLIENT_ADDRESS` | `1` to make a missing `FORWARDED_ALLOW_IPS` stop the start instead of a warning |

With `NODESTRO_BEHIND_PROXY=1` and no `FORWARDED_ALLOW_IPS`, `nodestro-server check` prints
`warning: proxy.client_address_unknown: …` and `nodestro-server api` logs the same warning and starts; with
`NODESTRO_REQUIRE_CLIENT_ADDRESS=1` both stop with that code (`check` as `not ready`). The check cannot see whether the
addresses in `FORWARDED_ALLOW_IPS` are the right ones: after a change, log in once and look for your own address (not
the proxy's) in the API's access log. The variables need nodestro-api with MUP-ONA A3 (the studio pin after it);
`FORWARDED_ALLOW_IPS` works with every version.

The proxy must replace or append to `X-Forwarded-For`, never pass a client's header through unchanged when it is the
first hop:

- **nginx:** `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` as in the example of
  [TLS reverse proxy](#tls-reverse-proxy). When nginx is the first hop, `$remote_addr` is the client; behind a load
  balancer, set `set_real_ip_from <load balancer>;` and `real_ip_header X-Forwarded-For;` so `$remote_addr` (and the
  appended address) is the client's.
- **Caddy:** `reverse_proxy` sets `X-Forwarded-For` by itself (the production example's `caddy reverse-proxy`
  does). It trusts incoming forwarding headers only from `trusted_proxies` (global `servers` option); leave it unset
  when Caddy is the first hop.
- **Traefik:** forwards `X-Forwarded-For` by itself. Incoming forwarding headers are trusted only from
  `entryPoints.<name>.forwardedHeaders.trustedIPs`; set it only to an upstream load balancer, never
  `insecure: true`.

`FORWARDED_ALLOW_IPS` then names the address the proxy connects from: `127.0.0.1` on the same host, the proxy
container's address in a compose network (`compose/production.example.yaml` gives Caddy a fixed address for this),
or the proxy hosts' addresses. Published API keys: failures of a well-formed key are counted per key id (its first 8
characters, never the secret) and only with a ten times higher limit per address, so a client's wrong key does not
throttle other keys even when every request has the proxy's address.

Residual risk (accepted): an operator who ignores the warning runs with shared per-address limits; one client can
then exhaust the login start budget of everyone behind the proxy for up to a minute. Keep the proxy's own rate limit
for `/api/auth/` (see above) as the first line.

## Run budget decisions

An attended run whose next model request does not fit its budget pauses before the request is sent and waits for a
decision (Studio: the run, the Approvals page). While it waits it holds no worker and no job; the decision, made in
the API process, queues it again and any worker continues it from its checkpoint. The worker's periodic sweep
(`NODESTRO_WORKER_REAP_SECONDS`) expires unanswered requests after the tenant's `budget_decision_hours` (default 24)
and continues runs whose decision the deciding process could not hand over. Only the person who started the run or
a tenant admin decides; viewers read. Schedules, batches, test series and published APIs never wait: their runs
fail with `run.budget_exceeded` as before. Every request and decision is in the tenant's budget audit trail.

## Health checks

`GET /api/health` needs no session. It answers 200 `{"status": "ok", "database": "ok"}` while the API process
reaches its database, and 503 `{"status": "unavailable", "database": "unreachable"}` when it does not (the check
gives up after 2 seconds): use it as the liveness check. `GET /api/ready` ("Metrics and status") is the readiness
check: it also answers 503 while the process starts or stops. The development stack and the production example check
the API with `/api/ready`; use it for your load balancer or orchestrator.

Workers have no HTTP port. With `NODESTRO_WORKER_HEARTBEAT_FILE` set (the stack and the production example use
`/tmp/nodestro-worker.json`, a path inside each worker's own container, never the shared data volume) a worker writes
a small heartbeat file every 10 seconds: its state, whether it reached the database at the last beat and which of its
loops run. The file holds no tenant data or secrets. `nodestro-server worker-health` reads it and exits `0` while the
worker is alive (also while it drains after `SIGTERM`), `1` when the file is missing or older than `--max-age` seconds
(default 60: the event loop is blocked or the process hangs), the worker could not reach its database or one of its
loops ended, and `2` when the variable is unset. The stack uses it as the worker's health check.
`nodestro-server check --skip-identity-provider` remains the configuration and database check for a worker (it
leaves out the identity provider, which only the API uses); it does not see a hung worker.

Server export jobs (`NODESTRO_SERVER_EXPORT_JOBS`, off by default until their review) are built by the workers: if
you switch them on, set the switch and the export limits on the workers as well as on the API, and give the workers
the same data volume.

## Metrics and status

`GET /api/metrics` serves Prometheus metrics when `NODESTRO_METRICS_TOKEN` (or `_FILE`, at least 32 characters, e.g.
`openssl rand -hex 32`) is set; without it the route does not exist. The scraper sends
`Authorization: Bearer <token>`; anything else gets 401. It needs no `NODESTRO_AXENTRA=on` (the image has the
package). The output has no tenant, user, run or workflow labels and no secrets. Scrape each API process directly
(the in-process counters are per process); database-derived values are refreshed at most once a minute. Keep the path
away from the public internet in the proxy if your scraper can reach the API on the private network:

```nginx
location = /api/metrics { allow 10.0.0.0/8; deny all; proxy_pass http://127.0.0.1:8080; }
```

Useful series and alerts (names and labels in nodestro-runtime `docs/AXENTRA.md`, "Observability"):

| Series | Watch for |
| --- | --- |
| `nodestro_db_pool_requests_waiting{pool}`, `nodestro_db_pool_in_use{pool}` | waiting clients for more than a few minutes: raise the pool size or `max_connections` |
| `nodestro_jobs{status="queued"}`, `nodestro_jobs_oldest_queued_seconds`, `nodestro_workers_active` | a growing queue or no active worker |
| `nodestro_jobs_expired_leases` | above 0 for longer than the reap interval: workers die or hang |
| `nodestro_integration_operations_total{outcome="failed"}` | mirror writes or notifications failing (run `axentra reconcile`) |
| `nodestro_integration_operations_total{operation="secret_decrypt",outcome="unreadable"}` | stored secrets that cannot be read |
| `nodestro_axentra_reconcile_backlog{kind}` | records not yet mirrored (should stay near 0 while the mirrors are on) |
| `nodestro_axentra_migrations_pending`, `nodestro_schema_version` | a schema behind the code after an upgrade |

The worker has no HTTP port and exposes no metrics of its own; its work shows in the database-derived series.
`nodestro-server axentra status` prints the embedding state for operators: switches, both schema runners, keyring key
ids (never keys), stored secrets by format, the identity backend and whether it would start, and the reconcile
backlog. Run events and their live streams are unchanged; they are not notifications.

`GET /api/ready` (no login) answers `200 {"status": "ready"}` only while the API process serves and reaches its
database, and `503` while it starts, stops or loses the database: use it as the load balancer's readiness check
and `/api/health` as the liveness check. Every answer carries `X-Request-ID` (a short id from the proxy is kept),
and the log lines of that request name it. `NODESTRO_LOG_FORMAT=json` writes one JSON object per log line
(`time`, `level`, `logger`, `message`, `request_id`, `exception`) for `api` and `worker`.

Batches and test series: the API process that runs one holds a 60-second lease. After an API process stopped,
its running batches show `interrupted` once their lease ran out; a member continues them in the studio.

Access audit: tenant admins read logins, API key changes and the operator's commands (`create-tenant`,
`set-role`, `remove-member`, `revoke-sessions`, `tenant suspend|resume`, recorded with the actor `operator`) at
`GET /api/access-audit`. With `NODESTRO_AXENTRA_AUDIT=1` they are also mirrored into Axentra's audit log.

## The sandbox daemon

Tool code, including code written by the Workflow Architect or the Assistant, is untrusted. The server runs it only
in containers: no network, read-only root file system, all capabilities dropped, as user `nobody`, with memory,
CPU and process limits, and without mounts of the host. Images are built by the server and never pulled when a
tool runs. There is no fallback: when the daemon is unreachable, tool code does not run and `check` reports
`sandbox.unavailable`.

Use a Docker daemon that does nothing else. Whoever controls a Docker daemon controls its host, so the server must
not get the host's own daemon or socket. Options, from most to least isolated:

- a dedicated VM that runs only Docker, reached over TCP with mutual TLS (`DOCKER_HOST=tcp://sandbox:2376`,
  `DOCKER_TLS_VERIFY=1`, client certificates in `DOCKER_CERT_PATH`);
- Docker-in-Docker in a privileged container on the server host, as in `compose/compose.yaml`; this isolates the
  sandbox's containers, images and network from the host's daemon, but a privileged container is not a security
  boundary against a kernel exploit.

On a host with AppArmor (Ubuntu, Debian) the sandbox daemon must confine its containers with an enforcing profile:
the server's self-test refuses unconfined containers there, and tool code does not run (Settings → Sandbox and
`GET /api/sandbox/status` name the failed check). The stock `docker:dind` image starts its containers unconfined (it has
no `apparmor_parser`, and its entrypoint sets `container=docker`, which makes containerd skip AppArmor);
`compose/sandbox/Dockerfile` adds the parser and starts `dockerd` without that variable, so the daemon confines its
containers with `docker-default`. A dedicated Docker VM with AppArmor does this by default.

Optionally use a stronger runtime for the sandbox daemon (gVisor `runsc`, Kata Containers).

The server builds an image per approved Python environment (`nodestro-env:<key>`) on the sandbox daemon and never
deletes one, also not when a tenant deletes the environment: images are shared by content, so another tenant's
environment with the same lock may use the same image. Remove unused `nodestro-env:*` images on the sandbox daemon
yourself (`docker image ls nodestro-env`, `docker image rm …`). An image that is still needed is built again on its
next use, which needs the package index.

## Backup and restore

Back up two things together, from the same point in time: the database and the data volume (`NODESTRO_DATA_DIR`,
the tenants' files, such as their input files). A dump and an archive taken while the API and the workers keep
writing do not match: a file uploaded between the two is in one and not in the other. Take a paired backup with
nothing running that writes:

1. Stop the API and all workers (a maintenance window; runs in progress are interrupted and can be continued
   afterwards, see [Upgrade](#upgrade)).
2. `nodestro-server backup /backups` (pg_dump, custom format: `/backups/nodestro-<time>.dump`).
3. `tar -C /var/lib/nodestro --exclude=./backups -czf /backups/nodestro-data-<time>.tar.gz .` (the data volume
   without the pre-migration dumps of `migrate --backup-dir`).
4. Record the files with their SHA-256 sums together, then start the API and the workers again.

`scripts/backup.sh DIR` does these steps for the development stack and writes `nodestro-backup-<time>.json` (the
dump, the data archive and the storage archive below, each with size and SHA-256, the image ID and the time);
`scripts/restore.sh DIR/nodestro-backup-<time>.json` checks every checksum before it changes anything and restores
the database and the data volume. The end-to-end test `test_a_paired_backup_restores_the_database_and_the_tenant_files`
runs both: an input file deleted after the backup is back with its bytes, one uploaded after it is gone. A
file system snapshot of the volume (LVM, ZFS, a cloud disk) taken while the API and the workers are stopped works the
same way and shortens the window.

With `NODESTRO_FILES_BACKEND=axentra` input file bytes live in Axentra's storage. On the local backend `backup` also
writes `/backups/nodestro-files-<time>.tar.gz` of `storage.local_path` (after the dump; uploads in progress left
out; before the first upload the archive is empty). On S3, back up the bucket with its own versioning or
replication. To restore, restore the dump, the data volume and the storage archive (or the bucket) of the same time,
then run `nodestro-server files verify`: it must print `"ok": true` (a file deleted between the dump and the archive
is reported as `input.content_missing`).

`backup` runs as the owner role (`NODESTRO_DATABASE_MIGRATION_URL`; it needs `BYPASSRLS` to read Axentra's tables, see
[Database roles](#database-roles)). Without that variable `pg_dump` runs as the runtime role, which row-level
security keeps from reading every row: `backup` then stops with `storage.backup_failed` and names the variable. With
`NODESTRO_DATABASE_SCHEMA` it dumps only that schema. It passes the database password to `pg_dump` in its
environment, never on the command line. Keep backups encrypted and off the server; they contain the tenants' data
(their provider keys stay encrypted with `NODESTRO_SECRET_KEY`, which you keep separately).

To restore:

1. Stop the API and all workers.
2. Restore the database in one transaction, connected as the owner role (the restored objects belong to the role
   that restores them; never restore as the runtime role):
   `python -I scripts/restore_dump.py <dump>` in the server image (it reads the owner role's connection from
   `/run/secrets/database_migration_url`). It does, in one transaction (`psql --single-transaction`):
   - leave the extensions (pgvector) out of `pg_restore --list` (the owner role cannot drop or create them, so
     `--clean` would stop at `DROP EXTENSION`);
   - drop the owner role's tables, views and sequences of the dump's schemas that are not in the dump (other schemas
     are left alone): a newer release's migrations created them, and one with a foreign key to a restored table
     would stop `--clean`;
   - apply `pg_restore --clean --if-exists --no-owner --use-list=<list> --file=- <dump>`.

   Two lines `WARNING: no privileges were granted for "public"` are expected when the owner role does not own the
   schema `public`: the dump repeats that schema's grants, which only its owner can give, and they stay as they are.
   Step 4 grants the runtime role its privileges again.

   Use the image's `pg_restore` and `psql` (version 17, like its `pg_dump`). Into a new database server, a superuser installs pgvector first (`roles.sql`). The client tools and the server must have the same major
   version: a dump written by `pg_dump` 17 cannot be read by an older `pg_restore`, and `pg_restore` 17 cannot
   restore into PostgreSQL 16 (it sets `transaction_timeout`). This is why the server needs PostgreSQL 17.
3. Restore the data volume from the archive of the same backup: remove its contents (keep `backups/` if you want
   the pre-migration dumps) and unpack the archive as the image's user (10001).
4. Run `nodestro-server migrate` (an older dump is migrated; a backup is taken first; the runtime role is granted its
   privileges again), then start the API and the workers. Into a new database server: create the roles first.

`scripts/restore.sh MANIFEST` does steps 1 to 4 for the development stack (with `files verify` when the backup has a
storage archive); `scripts/restore.sh DUMP` restores a dump alone (steps 1, 2 and 4). The end-to-end tests restore
backups both ways.

## Upgrade

1. Read the changelog of the new image.
2. Take a backup (above).
3. Stop the API and the workers, start the new image's `nodestro-server migrate --backup-dir /backups` (it runs
   `pg_dump` before it changes anything; `--backup-taken` states that you made one yourself), then start the new
   API and workers. A database written by a newer release is refused (`storage.schema_too_new`); downgrade by
   restoring the backup.

The CI job `upgrade` (`.github/workflows/upgrade.yml`) runs these steps and the rollback below against the
development stack, from the previous release in `tests/upgrade-from.json` to the current image.

PostgreSQL migrations 5 and 6 (added with the backend audit fixes) create and rebuild indexes on
`nodestro_documents` (6 makes the `status` and `trigger_ref` indexes partial, then runs `ANALYZE`). Building them
blocks writes to that table until they are done, which takes longer the more documents the database holds: plan a
short maintenance window, and take the backup first as above.

A run that was executing when its worker stopped is marked `run.interrupted` and waits for a person to continue
it; workers drain their current run on SIGTERM (give them a stop timeout longer than your longest run step). The
reaper also marks a run as interrupted that is stored as queued or running without an active job, once it has not
changed for twice the lease (120 seconds with the default `NODESTRO_WORKER_LEASE_SECONDS`).

**Owners of older assistant conversations.** Conversations created before conversations had an owner are visible
to the whole tenant. Run `nodestro-server assistant backfill-owners --dry-run` to see which ones get an owner (the
user who attached their files), then `nodestro-server assistant backfill-owners` (optionally `--tenant TENANT`).
Conversations without a known author stay visible to the tenant. The command is idempotent.

## Load test

`tests/e2e/load.py` loads a running development stack: `--tenants` new tenants start `--runs` runs each from
`--concurrency` threads against the model stub, with `--workers` worker processes, while the runs and usage views are
read; it prints run throughput, start latency, run duration and the list and usage latency as percentiles
(`--json FILE` keeps the report). Start the stack with `KEEP_STACK=1 scripts/e2e.sh -k test_the_configured_server_is_ready`
(or `docker compose up -d --wait`), then for example `python3 tests/e2e/load.py --tenants 4 --runs 50 --concurrency 24
--workers 3`. The model stub answers at once, so the figures are those of the API, the workers and PostgreSQL.

Measured only on a development machine so far, **not on target hardware** (2026-11-06, studio 58bb17d, 4 shared
virtual CPUs, the whole stack on the same machine, an otherwise busy host): 200 runs of 4 tenants with 3 workers and 24
concurrent clients all succeeded in 15.5 s (12.9 runs per second); start p50 0.29 s and p99 1.0 s, start to finished
p50 1.6 s and p99 4.8 s; `GET /api/runs` p50 0.06 s and p99 0.28 s and `GET /api/usage` p50 0.06 s and p99 0.53 s while
the runs were going, both about 0.015 s afterwards. Before a production pilot, run it on the target hardware with
realistic tenant, run and worker numbers and a database that already holds months of runs (`/api/usage` grows with the
number of runs).

## System requirements (tested)

What the acceptance tests ran on. Anything else is untested, not unsupported by design.

| Part | Tested | Not tested |
| --- | --- | --- |
| Container host | linux/amd64, Docker Engine with Compose v2 (GitHub `ubuntu-latest` runner, Ubuntu 24.04) | arm64, Podman, Kubernetes, Docker Desktop on macOS or Windows |
| Database | PostgreSQL 17 with pgvector 0.8.7 (`pgvector/pgvector:0.8.7-pg17`; the image's `pg_dump`/`pg_restore` are version 17) | PostgreSQL 16 and 18 (see below); managed PostgreSQL services |
| Identity provider | Dex v2.44.0 (OpenID Connect, authorization code with PKCE) | Keycloak, Entra ID, Okta, others (standard OIDC, expected to work) |
| Sandbox daemon | Docker-in-Docker 29.9.2 with TLS, a separate daemon from the host's | a remote Docker host on another machine |
| Browsers for the studio | Chromium (Playwright 1.63) against the server image behind Caddy over https: login through Dex, `__Host-` cookies, sign out, refusals (`scripts/browser-e2e.sh`) | Firefox, Safari against a server; the studio's full browser suites against a server with logins |

Other PostgreSQL major versions, checked once by hand (2026-11-07, `NODESTRO_POSTGRES_IMAGE` replaces the development
stack's database image, for example `pgvector/pgvector:0.8.7-pg16@sha256:0dd3149a…`):

- **PostgreSQL 16:** migrations, logins, tenants, runs, the worker and semantic search work, but restoring a backup
  fails: the image's `pg_dump` 17 writes `SET transaction_timeout`, which PostgreSQL 16 does not know. Do not use 16.
- **PostgreSQL 18:** the official images keep their data in `/var/lib/postgresql/18/docker` and refuse to start with
  a volume on `/var/lib/postgresql/data` (the development stack's mount), so the stack did not start; with 18 the
  volume belongs on `/var/lib/postgresql`. Backups would also need a `pg_dump` 18 (`pg_dump` refuses newer
  servers). Not tested further.

## Releases and rollback

A release has three separate steps. Only the last two publish anything, and each is started by a person.

1. **Candidate** (`.github/workflows/release.yml`, run by hand with the version, for example `v0.2.0-preview.1`): it
   builds the image from `studio.json` with the version in its labels, runs every acceptance test against it, saves
   it, scans the saved image and the release files for secrets (`scripts/scan_secrets.py`, including the build
   token's exact value), scans the image for known vulnerabilities (`scripts/scan-vulnerabilities.sh`, see below) and
   writes `release-manifest.json` and `SHA256SUMS`. The run's `release-candidate`
   artifact holds the saved image and those files. It pushes nothing and its token can only read.
2. **Publish** (`.github/workflows/publish.yml`, run by hand with the candidate's run ID, the version and the
   confirmation `publish <version>`): it checks that the run is a passed candidate on master, the checksums, the
   manifest's version and commit, and that the loaded image has the tested image ID. Then it pushes the image to
   `ghcr.io/peterkarlhuber/nodestro-server:<version>` (never `latest`) and creates a **draft pre-release** with the
   manifest, the checksums and `published-image.txt` (the image's registry digest). Required reviewers for the
   `release` environment (repository settings) add a second approval before this job runs.
3. **Release**: a person reviews the draft and publishes it; that creates the tag.

- Deploy by digest (`published-image.txt`), not by tag. `docker image inspect --format '{{.Id}}'` of a pulled image
  equals the ID in the manifest (`images`). The manifest also names every component commit, the license inventory
  of the image's Python packages and of the studio interface, the channel (`preview` for a version with a
  pre-release part) and the signing state.
- Images are **not signed** (no signing key is configured); the manifest says `"status": "unsigned"` and the image
  carries the labels `dev.nodestro.signing=unsigned` and `dev.nodestro.channel`. Preview versions are not meant for
  production data.
- Vulnerability scans: `scripts/scan-vulnerabilities.sh IMAGE [REPORT_DIR]` audits the image's Python packages
  (its pip freeze `/opt/nodestro/pinned.txt`, without the Nodestro components from git) with `pip-audit` and its
  operating system packages and binaries with Trivy (`scripts/scanner/Dockerfile`, pinned by digest, kept current by
  Dependabot) on the saved image. Any known Python vulnerability fails it, and so does a HIGH or CRITICAL finding
  that has a fixed version; findings without a fix (most of them in Debian packages of the base image) are listed in
  the reports only and go away with a base image refresh. Accepted findings go into
  `scripts/vulnerability-allow.txt` with their reason. CI scans both images (server and `local`) on every change and
  keeps the reports as the `vulnerability-reports` artifact; the candidate puts them into `release/vulnerabilities/`
  (they are not published).
- Rollback:
  1. Stop the API and the workers.
  2. If the newer release migrated the database, restore the backup that its `migrate` step wrote (see "Backup and
     restore"). An older image refuses a newer schema (`storage.schema_too_new`) instead of misreading it.
     The restore drops the tables, views and sequences that the newer release's migrations created; functions and
     types they created stay (the older release ignores them, a later upgrade replaces them). For an exact rollback,
     restore into a new, empty database instead (created by the owner role like the original, the roles already
     exist) and point `NODESTRO_DATABASE_URL` and `NODESTRO_DATABASE_MIGRATION_URL` at it.
  3. Start the previous image's `migrate`, then its API and workers.
- Supported: linux/amd64 images. The CI job `e2e-arm64` (added 2026-11-06) builds the image on a Linux arm64 runner
  and runs the acceptance tests there; arm64 counts as tested once that job has passed, and release candidates are
  still built for amd64 only.

## Production example

`compose/production.example.yaml` is an example of a production installation with Docker Compose, not a supported or
tested deployment form: an external PostgreSQL 17 with pgvector, your own OpenID Connect provider over https, a remote
sandbox Docker host over mutual TLS, Caddy as the TLS proxy (Let's Encrypt certificates, no access log, so setup links
and sign-in codes are never logged by it; the only published ports), one API and two workers with memory, CPU and
process limits, read-only root file systems and no capabilities, and `migrate` as a one-off command (`docker compose
run --rm migrate`, before the first start and after every image update). Its header lists the settings and files it
needs. CI only checks that it is a valid compose file. A Helm chart does not exist; which deployment forms are
supported is still to be decided.

## Development stack (Linux)

```sh
python3 scripts/dev-secrets.py                       # random secrets and dev passwords in compose/.secrets/
scripts/build-image.sh nodestro-server:dev            # NODESTRO_READ=<token> is optional
NODESTRO_IMAGE=nodestro-server:dev docker compose -f compose/compose.yaml up -d --wait
```

Open http://localhost:8080. The users `alice`, `bob` and `mallory` (`@example.com`) log in at Dex with the
passwords in `compose/.secrets/users.json`. Create a tenant and its setup link with
`docker compose -f compose/compose.yaml run --rm api create-tenant acme Acme` and `… run --rm api setup-link acme`.
To try roles other than owner, let `bob` log in once and then run
`… run --rm api set-role acme bob@example.com editor` and type the user id it shows. The API and the worker use the host's network (so
`localhost` means the same to the browser and the server), which is why the stack is Linux-only. Dex keeps its state in memory and the model stub answers from a script: neither
is for production.

`scripts/e2e.sh` starts the stack from scratch, runs the acceptance tests in `tests/e2e` and removes the stack.
With `NODESTRO_E2E_ALL_SWITCHES=1` it layers `compose/all-switches.yaml`, which turns every Axentra switch of
[Axentra platform services](#axentra-platform-services-optional-off-by-default) on for `migrate`, the API and the
worker (keyring and metrics token from `scripts/dev-secrets.py`, input files in a directory of the data volume, the
API and the worker still as `nodestro_app`), and also runs `tests/e2e/test_all_switches.py`. That file is for the
development stack only; it approves no switch for production.

`scripts/browser-e2e.sh` starts the same stack behind Caddy as the TLS proxy (`tests/e2e/tls-proxy.yaml`: the public
origin and Dex's redirect address become `https://localhost:8443`, Caddy's certificate comes from its own local
authority, no access log) and runs the Chromium test `tests/e2e/browser.mjs` (see the README). It uses the same
compose project and ports as `scripts/e2e.sh`, so run one after the other.

## Security notes

- No route of the studio answers without a session, except the login itself, `/api/health` and the static web
  interface; the API reference (`/api/docs`, `/api/openapi.json`) needs a login too. Changing requests must come
  from the studio's origin. Sessions are random tokens; the database holds only their hashes.
- A login is bound to the browser that started it: `/api/auth/login` sets a `__Host-nodestro-login` cookie (valid
  for 10 minutes) that must match the login's `state` at `/api/auth/callback`; otherwise the callback answers 400
  `identity.login_expired`.
- The server's access log never contains the values of `setup`, `code` and `state` query parameters (setup links and
  sign-in codes); they are replaced by `[redacted]`. The reverse proxy logs them unless it is configured not to (see
  [TLS reverse proxy](#tls-reverse-proxy)).
- Run, Workflow Architect and assistant event streams end within about 15 seconds after the viewer's session or
  membership ends.
- Every request is bound to the session's tenant; a tenant's data is never visible to another tenant.
- Tenants reach only the model endpoints in `NODESTRO_MODEL_ENDPOINTS` besides the providers' public APIs, so the
  server cannot be used to probe its own network, as long as the list stays narrow (see
  [Semantic knowledge search and local models](#semantic-knowledge-search-and-local-models)).
- Amazon Bedrock: tenants never use the server's own AWS credentials, only the role the operator assigned them in
  `NODESTRO_BEDROCK_TENANT_ROLES`; there are no custom Bedrock endpoints. The server's base identity needs only
  `sts:AssumeRole`. On EC2, require IMDSv2 with hop limit 1 (see [Amazon Bedrock for tenants](#amazon-bedrock-for-tenants)).
- Secrets never appear in logs, errors or the image. The component repositories are public; a build token, if
  given, reaches the build only as a BuildKit secret.
- Live run chat (LRC-1): questions and instructions to an orchestrator of a running run are stored in the tenant's
  database (`run_messages`); the worker that executes the run reads them at the orchestrator's next decision, so
  they survive restarts and worker changes, and a worker that lost its lease delivers none. Answers to questions
  are model calls of the API process (at most 4 at once per process), limited per run (`NODESTRO_RUN_CHAT_BUDGET_USD`,
  default 0.50; `NODESTRO_RUN_CHAT_MAX_QUESTIONS`, default 30; `NODESTRO_RUN_CHAT_MAX_INSTRUCTIONS` per orchestrator,
  default 20) and recorded in the usage log (`run_chat`). Runs started by schedules, batches, test series or APIs
  take instructions only when the workflow's orchestrator allows it (`live_steering: always`).
- Not yet: rotation of `NODESTRO_SECRET_KEY` without Axentra (with Axentra: the keyring, see above); published workflow APIs on a server (calls are answered with 405).
  Batches and test series are driven by the API process that started them: it reads their runs, which the workers
  execute, from the database every two seconds, and holds a 60-second lease on it. If that API process stops, the
  batch or series shows `interrupted` once the lease ran out and a member continues it; its runs themselves finish
  on the workers.
