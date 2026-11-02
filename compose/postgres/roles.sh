#!/bin/sh
# Create or update the server's database roles (roles.sql) as the superuser. Runs in the postgres image: as the
# one-shot `db-roles` service on every `docker compose up` (existing databases too). The passwords come from secret
# files (psql reads the roles' files itself), never on a command line.
set -eu
export PGPASSWORD="$(cat /run/secrets/postgres_password)"
exec psql --no-psqlrc --quiet --host="${PGHOST:-postgres}" --username="${POSTGRES_USER:-nodestro}" \
  --dbname="${POSTGRES_DB:-nodestro}" \
  --file=/etc/nodestro/roles.sql
