-- The server's database roles (docs/RUNBOOK.md, "Database roles"). Run as a superuser; idempotent, safe to repeat on
-- every start. The passwords are read from /run/secrets/postgres_owner_password and postgres_app_password (or the psql
-- variables owner_password and app_password); the role names default to nodestro_owner and nodestro_app.
--
--   nodestro_owner  owns the tables: runs `nodestro-server migrate`, backups (pg_dump), restores and
--                   `db grant-runtime-role`. NOSUPERUSER, but BYPASSRLS: pg_dump must read every row of the tables
--                   with forced row-level security (Axentra's).
--   nodestro_app    the API and the worker (NODESTRO_DATABASE_URL). No superuser, no BYPASSRLS, owns nothing: row-level
--                   security applies to it. Its table privileges are granted by `migrate` (as the owner).
--
-- pgvector (the extension `vector`) is installed when the server has it: semantic knowledge search ranks vectors in the
-- database then (nodestro-runtime migration 0010). pgvector is not a trusted extension, so the owner role cannot
-- install it itself; without it the runtime ranks the vectors.
--
-- An existing database whose tables a superuser created (the development setup before these roles) is moved over:
-- the tables, views, sequences, functions and types of the public schema that the connecting superuser owns are given
-- to the owner role. Nothing is dropped, nothing is rewritten.
\set ON_ERROR_STOP on
\if :{?owner_role}
\else
  \set owner_role nodestro_owner
\endif
\if :{?app_role}
\else
  \set app_role nodestro_app
\endif
\if :{?owner_password}
\else
  \set owner_password `cat /run/secrets/postgres_owner_password`
\endif
\if :{?app_password}
\else
  \set app_password `cat /run/secrets/postgres_app_password`
\endif

SELECT format('CREATE ROLE %I LOGIN', :'owner_role') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'owner_role')
\gexec
SELECT format('CREATE ROLE %I LOGIN', :'app_role') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_role')
\gexec
SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS PASSWORD %L',
              :'owner_role', :'owner_password')
\gexec
SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
              :'app_role', :'app_password')
\gexec

-- Connect to this database; nobody but the owner creates objects in the public schema.
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I, %I', current_database(), :'owner_role', :'app_role')
\gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('GRANT USAGE, CREATE ON SCHEMA public TO %I', :'owner_role')
\gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_role')
\gexec

-- Objects of the public schema owned by the connecting superuser (an older setup) go to the owner role. Sequences
-- that belong to a table move with it. One transaction: all or nothing.
BEGIN;
SELECT format('ALTER %s %s OWNER TO %I',
              CASE c.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' WHEN 'S' THEN 'SEQUENCE'
                             WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END,
              c.oid::regclass, :'owner_role')
  FROM pg_class c
 WHERE c.relnamespace = 'public'::regnamespace
   AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
   AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
   AND NOT (c.relkind = 'S' AND EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                                           AND d.objid = c.oid AND d.deptype IN ('a', 'i')))
 ORDER BY c.relkind = 'S', c.relname
\gexec
SELECT format('ALTER ROUTINE %s OWNER TO %I', p.oid::regprocedure, :'owner_role')
  FROM pg_proc p
 WHERE p.pronamespace = 'public'::regnamespace
   AND p.proowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
   AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid
                     AND d.deptype = 'e')
\gexec
SELECT format('ALTER TYPE %s OWNER TO %I', t.oid::regtype, :'owner_role')
  FROM pg_type t
 WHERE t.typnamespace = 'public'::regnamespace
   AND t.typowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
   AND t.typtype IN ('e', 'd', 'c', 'r', 'm')
   AND (t.typtype <> 'c' OR (SELECT relkind FROM pg_class WHERE oid = t.typrelid) = 'c')
   AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid
                     AND d.deptype = 'e')
\gexec
COMMIT;

-- pgvector, where the server has it (the development stack's image does). Idempotent; an installed version is kept
-- (update it with ALTER EXTENSION vector UPDATE after a new image).
SELECT 'CREATE EXTENSION IF NOT EXISTS vector'
 WHERE EXISTS (SELECT FROM pg_available_extensions WHERE name = 'vector')
\gexec
