# Changelog

## Unreleased

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
