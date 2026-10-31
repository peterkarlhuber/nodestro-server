# nodestro-server

The Nodestro server: one image with the studio (web interface and API), its workers and the operator commands,
plus a development stack and the end-to-end acceptance tests.

- `image/`: the image. `studio.json` names the nodestro-studio commit it is built from; that commit pins every
  component by full commit SHA. `scripts/build-image.sh` builds it.
- `compose/`: the development and test stack (Linux): PostgreSQL 17, Dex as the identity provider, an isolated
  Docker daemon for tool code (Docker-in-Docker with TLS), an OpenAI-compatible model stub, and the server's
  `migrate`, `api` and `worker`.
- `tests/e2e/`: acceptance tests that drive the running stack like browsers and operators do.
- `docs/RUNBOOK.md`: installation, tested system requirements, configuration, TLS proxy, the sandbox daemon, backup
  and restore, upgrades, releases.

## Quick start (development, Linux)

```sh
python3 scripts/dev-secrets.py
NODESTRO_READ=<token> scripts/build-image.sh nodestro-server:dev
NODESTRO_IMAGE=nodestro-server:dev docker compose -f compose/compose.yaml up -d --wait
docker compose -f compose/compose.yaml run --rm api create-tenant acme Acme
docker compose -f compose/compose.yaml run --rm api setup-link acme   # open the link, log in as alice
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
| A worker killed in the middle of a run | `test_a_worker_killed_in_the_middle_of_a_run` |
| Backup and restore with `pg_dump` | `test_backup_and_restore_with_pg_dump` |

Behind a TLS-inspecting proxy, set `NODESTRO_EXTRA_CA_FILE` to its certificate bundle (the scripts add
`compose/extra-ca.yaml`).

## Limitations

- Preview: builds are **unsigned**, only linux/amd64 is built and tested, and no browser has been tested against
  a server (see the runbook's system requirements).
- The development stack is Linux-only (the server containers use the host's network). Production installations
  follow the runbook on any Docker host.
- Dex and the model stub are for development and tests only.
- Base images are referenced by tag, not by digest.
- The server's secret key cannot be rotated yet.

## License

See [LICENSE](LICENSE).
