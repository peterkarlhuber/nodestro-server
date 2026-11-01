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
| PostgreSQL 17 | All data of all tenants | Back it up (see below); the image's `pg_dump`/`pg_restore` are version 17 |
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
2. Create the database and a role that owns it:
   `CREATE ROLE nodestro LOGIN PASSWORD '…'; CREATE DATABASE nodestro OWNER nodestro;`
3. Register a client at your identity provider: confidential client, authorization code flow with PKCE (S256),
   redirect URI `https://<studio host>/api/auth/callback`, scopes `openid email profile`.
4. Generate the server's secret key once and keep it with your other secrets: `openssl rand -base64 32`.
   It encrypts the tenants' provider keys. Without it they cannot be read; there is no rotation yet.
5. Prepare the sandbox host (see [The sandbox daemon](#the-sandbox-daemon)).
6. Run `nodestro-server migrate`, then start the API and the workers, then the proxy.
7. Create the first tenant and its owner:
   `nodestro-server create-tenant acme "Acme Inc."` and `nodestro-server setup-link acme`. The link is valid for
   24 hours and once; whoever logs in with it becomes the tenant's first owner.
8. Add everyone else (see [Members](#members)): each person logs in once (they are told that they have no access
   yet), then an operator grants a role, for example `nodestro-server set-role acme bob@example.com editor`.

## Members

Members are managed with operator commands; they cannot be managed in the studio yet. `USER` is a user id
(`u_…`), a verified e-mail address (compared case-insensitively) or the person's subject at the identity provider.
The person must have logged in once, so that the server knows them.

| Command | What it does |
| --- | --- |
| `nodestro-server members TENANT` | Lists the members with user id, role, e-mail address, name and subject |
| `nodestro-server set-role TENANT USER ROLE` | Adds the person to the tenant or changes their role (`owner`, `admin`, `editor`, `operator`, `viewer`); takes effect with their next request |
| `nodestro-server remove-member TENANT USER` | Removes the person from the tenant and ends their sessions there |
| `nodestro-server revoke-sessions USER` | Ends every session of the person in every tenant (logs them out everywhere; memberships stay) |

Errors: `identity.user_unknown` (nobody with that name has logged in yet), `identity.user_ambiguous` (the e-mail
address names several users; use the user id), `identity.tenant_unknown`, `identity.not_a_member` and
`identity.last_owner` (a tenant keeps at least one owner).

## Configuration

Every setting comes from the environment. A `…_FILE` variable names a file holding the value instead (container
secrets); giving both forms is refused. Nothing has a default that weakens the server.

| Variable | Meaning |
| --- | --- |
| `NODESTRO_PROFILE` | `server` (set in the image) |
| `NODESTRO_DATABASE_URL` / `_FILE` | PostgreSQL connection (`host=… port=… user=… dbname=… password=…` or a URL) |
| `NODESTRO_PUBLIC_ORIGIN` | `https://studio.example.com` as browsers see it (`http://` only for localhost) |
| `NODESTRO_OIDC_ISSUER` | The provider's issuer URL (https; `http://` only for localhost) |
| `NODESTRO_OIDC_CLIENT_ID` | The client registered for the studio |
| `NODESTRO_OIDC_CLIENT_SECRET` / `_FILE` | Its secret |
| `NODESTRO_SECRET_KEY` / `_FILE` | At least 32 random bytes, base64 |
| `NODESTRO_MODEL_ENDPOINTS` | Comma-separated origins of self-hosted model endpoints tenants may use (Ollama, vLLM, …). Empty: none |
| `NODESTRO_WORKER_LEASE_SECONDS` | How long a run stays a worker's without a heartbeat (default 60) |
| `NODESTRO_WORKER_POLL_SECONDS`, `NODESTRO_WORKER_REAP_SECONDS` | Worker intervals (defaults 1 and 15) |
| `NODESTRO_WORKER_CLEANUP_SECONDS` | How often the scheduler leader cleans up (default 600): it deletes expired sessions and abandoned login starts, finished jobs after 7 days and run events after 2 days (the runs themselves stay) |
| `NODESTRO_DATABASE_POOL_SIZE` | Database connections per API or worker process (default 8) |
| `NODESTRO_DATABASE_STATEMENT_TIMEOUT` | Longest time one SQL statement may run, in seconds (default 30; 0: no limit). Migrations have no limit |
| `NODESTRO_DATABASE_IDLE_IN_TRANSACTION_TIMEOUT` | Longest time a transaction may stay idle, in seconds (default 300) |
| `NODESTRO_RUN_THREADS` | Threads for agents and orchestrator decisions of one tenant in one process (default 32); an agent beyond the limit waits for a thread |
| `NODESTRO_DATA_DIR` | Files of the tenants (`/var/lib/nodestro` in the image): a shared volume for API and workers |
| `DOCKER_HOST`, `DOCKER_TLS_VERIFY`, `DOCKER_CERT_PATH` | The sandbox daemon (TLS with client certificates) |
| `NODESTRO_BUILD_CA_FILE`, `SSL_CERT_FILE` | Only behind a TLS-inspecting proxy: its certificate bundle |

`nodestro-server check` validates all of it and exits with 0 when the server is ready. An incomplete or unsafe
configuration is refused with `profile.invalid`, listing every problem at once; secret values are never printed.

The server never uses provider keys from its own environment for tenants: each tenant enters its own keys, which
are stored encrypted (AES-256-GCM, a key per tenant derived from `NODESTRO_SECRET_KEY`).

PostgreSQL's `max_connections` must cover every process: (`NODESTRO_DATABASE_POOL_SIZE` + 1 connection for locks)
× the number of API and worker processes, plus a few for operator commands such as `migrate` and `backup`. With the
defaults, one API and two workers need up to 27 connections. Every connection is checked before it is used, so a
connection the database dropped (a restart, a failover, a proxy's idle timeout) is replaced without restarting the
API or the workers.

## TLS reverse proxy

The API listens on plain http; put it behind a proxy that terminates TLS and forwards to it. The session cookie is
`__Host-` prefixed and `Secure`, so the studio works only over https (and on localhost for development).

```nginx
server {
    listen 443 ssl;
    server_name studio.example.com;
    ssl_certificate     /etc/ssl/studio.pem;
    ssl_certificate_key /etc/ssl/studio.key;
    client_max_body_size 100m;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;            # run events are streamed
        proxy_read_timeout 1h;
    }
}
```

Bind the API to `127.0.0.1` or a private network (`nodestro-server api --host 127.0.0.1`); never publish port 8080.

The server has no rate limit for logins of its own, so a rate limit for `/api/auth/` in the proxy is still advisable
(for nginx: a `limit_req_zone` in the `http` block and a `location /api/auth/` with `limit_req` and the same
`proxy_*` settings). The server serves the studio gzip-compressed, with long-lived immutable caching for the
content-hashed files under `/assets` and `no-cache` for `index.html`, so the proxy need not compress it.

## Health checks

`GET /api/health` needs no session. It answers 200 `{"status": "ok", "database": "ok"}` while the API process
reaches its database, and 503 `{"status": "unavailable", "database": "unreachable"}` when it does not (the check
gives up after 2 seconds). The development stack's health check for the API treats the 503 as unhealthy; use the
same route for your load balancer or orchestrator. Workers have no HTTP port: the stack checks them with
`nodestro-server check`.

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

Optionally use a stronger runtime for the sandbox daemon (gVisor `runsc`, Kata Containers).

The server builds an image per approved Python environment (`nodestro-env:<key>`) on the sandbox daemon and never
deletes one, also not when a tenant deletes the environment: images are shared by content, so another tenant's
environment with the same lock may use the same image. Remove unused `nodestro-env:*` images on the sandbox daemon
yourself (`docker image ls nodestro-env`, `docker image rm …`). An image that is still needed is built again on its
next use, which needs the package index.

## Backup and restore

Back up two things together: the database and the data volume (`NODESTRO_DATA_DIR`, the tenants' files).

```sh
nodestro-server backup /backups          # pg_dump, custom format: /backups/nodestro-<time>.dump
tar -C /var/lib/nodestro -czf /backups/nodestro-data-<time>.tar.gz .
```

`backup` passes the database password to `pg_dump` in its environment, never on the command line. Keep backups
encrypted and off the server; they contain the tenants' data (their provider keys stay encrypted with
`NODESTRO_SECRET_KEY`, which you keep separately).

To restore:

1. Stop the API and all workers.
2. Restore the database in one transaction:
   `pg_restore --clean --if-exists --no-owner --single-transaction --exit-on-error -d <database> <dump>`, with the
   image's `pg_restore` (version 17, like its `pg_dump`). The client tools and the server must have the same major
   version: a dump written by `pg_dump` 17 cannot be read by an older `pg_restore`, and `pg_restore` 17 cannot
   restore into PostgreSQL 16 (it sets `transaction_timeout`). This is why the server needs PostgreSQL 17.
3. Restore the data volume from the archive of the same time.
4. Run `nodestro-server migrate` (an older dump is migrated; a backup is taken first), then start the API and the
   workers.

`scripts/restore.sh DUMP` does steps 1, 2 and 4 for the development stack; the end-to-end tests restore a backup
this way.

## Upgrade

1. Read the changelog of the new image.
2. Take a backup (above).
3. Stop the API and the workers, start the new image's `nodestro-server migrate --backup-dir /backups` (it runs
   `pg_dump` before it changes anything; `--backup-taken` states that you made one yourself), then start the new
   API and workers. A database written by a newer release is refused (`storage.schema_too_new`); downgrade by
   restoring the backup.

PostgreSQL migrations 5 and 6 (added with the backend audit fixes) create and rebuild indexes on
`nodestro_documents` (6 makes the `status` and `trigger_ref` indexes partial, then runs `ANALYZE`). Building them
blocks writes to that table until they are done, which takes longer the more documents the database holds: plan a
short maintenance window, and take the backup first as above.

A run that was executing when its worker stopped is marked `run.interrupted` and waits for a person to continue
it; workers drain their current run on SIGTERM (give them a stop timeout longer than your longest run step). The
reaper also marks a run as interrupted that is stored as queued or running without an active job, once it has not
changed for twice the lease (120 seconds with the default `NODESTRO_WORKER_LEASE_SECONDS`).

## System requirements (tested)

What the acceptance tests ran on. Anything else is untested, not unsupported by design.

| Part | Tested | Not tested |
| --- | --- | --- |
| Container host | linux/amd64, Docker Engine with Compose v2 (GitHub `ubuntu-latest` runner, Ubuntu 24.04) | arm64, Podman, Kubernetes, Docker Desktop on macOS or Windows |
| Database | PostgreSQL 17 (the image's `pg_dump`/`pg_restore` are version 17) | other major versions |
| Identity provider | Dex v2.44.0 (OpenID Connect, authorization code with PKCE) | Keycloak, Entra ID, Okta, others (standard OIDC, expected to work) |
| Sandbox daemon | Docker-in-Docker 29.9.2 with TLS, a separate daemon from the host's | a remote Docker host on another machine |
| Browsers for the studio | none against the server image: the acceptance tests use HTTP clients | Chromium, Firefox, Safari against a server |

## Releases and rollback

A release has three separate steps. Only the last two publish anything, and each is started by a person.

1. **Candidate** (`.github/workflows/release.yml`, run by hand with the version, for example `v0.2.0-preview.1`): it
   builds the image from `studio.json` with the version in its labels, runs every acceptance test against it, saves
   it, scans the saved image and the release files for secrets (`scripts/scan_secrets.py`, including the build
   token's exact value) and writes `release-manifest.json` and `SHA256SUMS`. The run's `release-candidate`
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
- Rollback:
  1. Stop the API and the workers.
  2. If the newer release migrated the database, restore the backup that its `migrate` step wrote (see "Backup and
     restore"). An older image refuses a newer schema (`storage.schema_too_new`) instead of misreading it.
  3. Start the previous image's `migrate`, then its API and workers.
- Supported: linux/amd64 images (the e2e tests run on that platform only). The Dockerfile also has an arm64 docker
  CLI checksum, but no arm64 image is built or tested.

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
`… run --rm api set-role acme bob@example.com editor`. The API and the worker use the host's network (so
`localhost` means the same to the browser and the server), which is why the stack is Linux-only. Dex keeps its state in memory and the model stub answers from a script: neither
is for production.

`scripts/e2e.sh` starts the stack from scratch, runs the acceptance tests in `tests/e2e` and removes the stack.

## Security notes

- No route of the studio answers without a session, except the login itself, `/api/health` and the static web
  interface; the API reference (`/api/docs`, `/api/openapi.json`) needs a login too. Changing requests must come
  from the studio's origin. Sessions are random tokens; the database holds only their hashes.
- A login is bound to the browser that started it: `/api/auth/login` sets a `__Host-nodestro-login` cookie (valid
  for 10 minutes) that must match the login's `state` at `/api/auth/callback`; otherwise the callback answers 400
  `identity.login_expired`.
- The access log never contains the values of `setup`, `code` and `state` query parameters (setup links and sign-in
  codes); they are replaced by `[redacted]`.
- Run, Workflow Architect and assistant event streams end within about 15 seconds after the viewer's session or
  membership ends.
- Every request is bound to the session's tenant; a tenant's data is never visible to another tenant.
- Tenants reach only the model endpoints in `NODESTRO_MODEL_ENDPOINTS` besides the providers' public APIs, so the
  server cannot be used to probe its own network.
- Secrets never appear in logs, errors or the image. The component repositories are public; a build token, if
  given, reaches the build only as a BuildKit secret.
- Live run chat (LRC-1): questions and instructions to an orchestrator of a running run are stored in the tenant's
  database (`run_messages`); the worker that executes the run reads them at the orchestrator's next decision, so
  they survive restarts and worker changes, and a worker that lost its lease delivers none. Answers to questions
  are model calls of the API process (at most 4 at once per process), limited per run (`NODESTRO_RUN_CHAT_BUDGET_USD`,
  default 0.50; `NODESTRO_RUN_CHAT_MAX_QUESTIONS`, default 30; `NODESTRO_RUN_CHAT_MAX_INSTRUCTIONS` per orchestrator,
  default 20) and recorded in the usage log (`run_chat`). Runs started by schedules, batches, test series or APIs
  take instructions only when the workflow's orchestrator allows it (`live_steering: always`).
- Not yet: rotation of `NODESTRO_SECRET_KEY`; published workflow APIs on a server (calls are answered with 405);
  batches and test series (their runs end on the workers, but the batch or series stays `running`, because the
  API process that started it does not learn that they ended). Do not offer these as supported server functions.
