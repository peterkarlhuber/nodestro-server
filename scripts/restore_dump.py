"""Restore a pg_dump (custom format) into the database of ``/run/secrets/database_migration_url``, in one transaction.

    python -I restore_dump.py DUMP

Runs inside the server image (its ``pg_restore`` and ``psql`` are version 17, like its ``pg_dump``), connected as the
owner role: the restored objects belong to the role that restores them. ``scripts/restore.sh`` and the upgrade test
use it; docs/RUNBOOK.md describes the same steps.

- Extensions (pgvector) are left out: a superuser installs them (``compose/postgres/roles.sql``), and the owner role
  may neither drop nor create them, so ``--clean`` would stop at ``DROP EXTENSION``.
- Tables, views and sequences of the owner role that are not in the dump are dropped first, but only in the schemas
  the dump contains (a dump of one schema, ``NODESTRO_DATABASE_SCHEMA``, never touches the role's other schemas): a
  newer release's migrations created them (a rollback to the backup its ``migrate`` step wrote), and one that refers
  to a restored table (a foreign key) would stop ``--clean`` from dropping that table's constraints. The dump's
  schemas then hold exactly the dump's tables, and a later upgrade migrates them again.
- Both steps run in one transaction (``psql --single-transaction``): if any statement fails, nothing changes.

The password goes to the tools in their environment, never on the command line.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

#: ``pg_restore --list`` lines of extensions and their comments.
EXTENSION = re.compile(r"^\d+; \d+ \d+ (EXTENSION - |COMMENT - EXTENSION )")
#: ``pg_restore --list`` lines of relations: ``<id>; <class> <oid> <TYPE> <schema> <name> <owner>``.
RELATION = re.compile(r"^\d+; \d+ \d+ (TABLE|VIEW|MATERIALIZED VIEW|SEQUENCE) (\S+) (\S+) \S+$")
#: ``pg_restore --list`` lines of schemas: ``<id>; <class> <oid> SCHEMA - <name> <owner>``.
SCHEMA = re.compile(r"^\d+; \d+ \d+ SCHEMA - (\S+) \S+$")
#: Relations of the owner role in the dump's schemas that are not part of an extension.
OWNED = """
SELECT n.nspname, c.relname, c.relkind
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S')
  AND pg_get_userbyid(c.relowner) = current_user
  AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\\_%%'
  AND n.nspname = ANY(%s)
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
                  AND d.deptype = 'e')
ORDER BY n.nspname, c.relname
"""
DROP = {"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW", "S": "SEQUENCE"}


def main(dump: str) -> int:
    with open("/run/secrets/database_migration_url", encoding="utf-8") as file:
        parts = conninfo_to_dict(file.read().strip())
    environment = dict(os.environ)
    password = parts.pop("password", None)
    if password is not None:
        environment["PGPASSWORD"] = str(password)
    target = make_conninfo("", **parts)

    listing = subprocess.run(["pg_restore", "--list", dump], capture_output=True, text=True, check=True).stdout
    kept = [line for line in listing.splitlines() if not EXTENSION.match(line)]
    in_dump = {(match[2], match[3]) for line in kept if (match := RELATION.match(line))}
    # Only the schemas the dump contains: a dump of one schema leaves the role's other schemas alone.
    schemas = sorted({schema for schema, _ in in_dump} | {m[1] for line in kept if (m := SCHEMA.match(line))})

    with psycopg.connect(target, **({"password": str(password)} if password is not None else {})) as connection:
        owned = connection.execute(OWNED, (schemas,)).fetchall()
        drops = [
            sql.SQL("DROP {} IF EXISTS {} CASCADE;")
            .format(sql.SQL(DROP[kind]), sql.Identifier(schema, name))
            .as_string(connection)
            for schema, name, kind in owned
            if (schema, name) not in in_dump
        ]

    with tempfile.TemporaryDirectory() as work:
        chosen = os.path.join(work, "restore.list")
        with open(chosen, "w", encoding="utf-8") as file:
            file.writelines(line + "\n" for line in kept)
        prelude = os.path.join(work, "prelude.sql")
        with open(prelude, "w", encoding="utf-8") as file:
            file.writelines(statement + "\n" for statement in drops)
        restore = subprocess.Popen(
            ["pg_restore", "--clean", "--if-exists", "--no-owner", "--use-list=" + chosen, "--file=-", dump],
            stdout=subprocess.PIPE,
        )
        apply = subprocess.run(
            [
                "psql",
                "--no-psqlrc",
                "--quiet",
                "--output=/dev/null",
                "--single-transaction",
                "--set=ON_ERROR_STOP=1",
                "--dbname=" + target,
                "--file=" + prelude,
                "--file=-",
            ],
            stdin=restore.stdout,
            env=environment,
            check=False,
        )
        assert restore.stdout is not None
        restore.stdout.close()
        written = restore.wait()
    if written != 0:
        print(f"pg_restore could not read {dump} ({written})", file=sys.stderr)
        return written
    if apply.returncode != 0:
        print(f"restoring {dump} failed ({apply.returncode}); the database is unchanged", file=sys.stderr)
        return apply.returncode
    if drops:
        print(f"dropped {len(drops)} relation(s) that are not in the dump", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: restore_dump.py DUMP")
    sys.exit(main(sys.argv[1]))
