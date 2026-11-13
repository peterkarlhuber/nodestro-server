# nodestro-server

The Nodestro server: one image with the studio (web interface and API), its workers and the operator commands,
plus a development stack and the end-to-end acceptance tests.

- `image/`: the image. `studio.json` names the nodestro-studio commit it is built from; that commit's lock
  (`platform/internal.txt`, `platform/internal-server.txt`) pins every internal package by full commit SHA, and its
  `platform/uploaded-prior-to` bounds the third-party packages. A studio commit without the lock, the upload cutoff
  or `scripts/lock_check.py` fails the build. `scripts/build-image.sh` builds it.
- `compose/`: the development and test stack (Linux): PostgreSQL 17 with pgvector, Dex as the identity provider, an isolated
  Docker daemon for tool code (Docker-in-Docker with TLS), an OpenAI-compatible model stub, and the server's
  `migrate`, `api` and `worker`.
- `tests/e2e/`: acceptance tests that drive the running stack like browsers and operators do.
- `docs/RUNBOOK.md`: installation, members, tested system requirements, configuration, Amazon Bedrock for tenants
  (an IAM role per tenant, never the server's own AWS credentials), TLS proxy, health checks, the sandbox daemon,
  backup and restore, upgrades, releases.

## Quick start (development, Linux)

```sh
python3 scripts/dev-secrets.py
scripts/build-image.sh nodestro-server:dev            # NODESTRO_READ=<token> is optional
NODESTRO_IMAGE=nodestro-server:dev docker compose -f compose/compose.yaml up -d --wait
docker compose -f compose/compose.yaml run --rm api create-tenant acme Acme
docker compose -f compose/compose.yaml run --rm api setup-link acme   # open the link, log in as alice
# after bob logged in once (he has no access yet):
docker compose -f compose/compose.yaml run --rm api set-role acme bob@example.com editor
```

The development users and their passwords are in `compose/.secrets/users.json` (generated, never committed).

## Acceptance tests

```sh
NODESTRO_IMAGE=nodestro-server:dev scripts/e2e.sh -v
```

They start the stack from scratch and cover:

| Requirement | Test |
| --- | --- |
| An incomplete or unsafe configuration is refused (`profile.invalid`) | `test_an_incomplete_or_unsafe_configuration_is_refused` |
| Anonymous requests are refused | `test_anonymous_requests_are_refused`, `test_changing_requests_from_another_origin_are_refused` |
| Login through an OpenID Connect provider (Dex) | `test_login_through_the_identity_provider`, `test_a_wrong_password_or_an_account_without_tenant_gets_no_session` |
| No access across tenants; provider keys encrypted at rest | `test_tenants_never_see_each_others_data` |
| Only the model endpoints the operator allowed | `test_tenants_use_only_the_model_endpoints_the_operator_allowed` |
| Untrusted tool code runs only in containers of the sandbox daemon, never as a fallback on the host | `test_tool_code_runs_only_in_a_container_of_the_sandbox_daemon`, `test_without_the_sandbox_daemon_tool_code_does_not_run_at_all` |
| Amazon Bedrock is unavailable to a tenant without an operator role, although the server has AWS credentials; tool containers get no AWS variables | `test_bedrock_is_not_available_without_an_operator_role`, `test_tool_code_sees_no_aws_variables` |
| Semantic knowledge search: an index built through the operator's embedding endpoint (the stub's Ollama API), searched with pgvector, per tenant | `test_a_semantic_index_is_built_through_the_operators_embedding_endpoint` |
| A worker killed in the middle of a run | `test_a_worker_killed_in_the_middle_of_a_run` |
| A suspended tenant is closed (sessions, logins, its runs) until it is resumed | `test_a_suspended_tenant_is_closed_until_it_is_resumed` |
| Backup and restore with `pg_dump` | `test_backup_and_restore_with_pg_dump` |
| A paired backup (database and data volume at one point in time) restores the tenants' files too | `test_a_paired_backup_restores_the_database_and_the_tenant_files` |

`NODESTRO_E2E_ALL_SWITCHES=1 scripts/e2e.sh -v` runs the same tests with every Axentra migration switch on
(`compose/all-switches.yaml`, development and tests only), plus `tests/e2e/test_all_switches.py`: the switches and the
runtime role, `/api/metrics` with and without the token, logins through Axentra, `axs1` secrets, an upload in
Axentra's storage, the in-app inbox (`/api/notifications`) and the audit/usage mirrors.

Behind a TLS-inspecting proxy, set `NODESTRO_EXTRA_CA_FILE` to its certificate bundle (the scripts add
`compose/extra-ca.yaml`).

### Browser test (Chromium through the TLS proxy)

```sh
NODESTRO_IMAGE=nodestro-server:dev scripts/browser-e2e.sh      # Node.js 22+ and Playwright with Chromium
```

It starts the stack behind Caddy on `https://localhost:8443` (`tests/e2e/tls-proxy.yaml`, `NODESTRO_TLS_PORT`
changes the port) and runs `tests/e2e/browser.mjs` in Chromium: the proxy's certificate, a first login through a
setup link at Dex, the `__Host-nodestro-session` cookie (Secure, HttpOnly, SameSite=Lax, Path=/, no Domain), HSTS, the
signed-in studio without console errors, sign out and a second login started by the studio itself; and the refusals:
an untrusted certificate, plain http on the TLS port, a wrong password, an account without a tenant, and a sign-in
code taken to another browser. Chromium trusts only the proxy's certificate (its public key), nothing else. CI runs
it in the `e2e` job.

## Limitations

- Preview: builds are **unsigned**, only linux/amd64 is built and tested, and of the browsers only Chromium is
  tested against a server (see the runbook's system requirements).
- The development stack is Linux-only (the server containers use the host's network). Production installations
  follow the runbook on any Docker host.
- Dex and the model stub are for development and tests only.
- The image's base images and every image of the development stack (PostgreSQL with pgvector, Dex, the
  Docker-in-Docker base, Python) are pinned by digest.
- No local model server: self-hosted model endpoints (Ollama, vLLM) are the operator's (`NODESTRO_MODEL_ENDPOINTS`).
- The server's secret key cannot be rotated yet.

## Open work

Known gaps, follow-ups and untested platforms are listed in [docs/TODO.md](docs/TODO.md).

## License

See [LICENSE](LICENSE).
