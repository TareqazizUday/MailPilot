# MailPilot — client handover checklist

This document helps hand off MailPilot to a client team: database choice, environment variables, first deploy, backups, and knowledge base (pgvector) expectations.

## Recommended: managed PostgreSQL with `vector`

For most production handovers, use **managed PostgreSQL** where the **`vector` (pgvector) extension** is available (e.g. AWS RDS for PostgreSQL, Google Cloud SQL, Azure Database for PostgreSQL, Neon, Supabase, etc. — confirm in the provider’s documentation).

**Why this is the easiest for the client**

- Backups, patching, HA, and monitoring are largely handled by the platform.
- Your application already uses a **DSN** for the Django DB (`DJANGO_DB_*` in [`.env.example`](../.env.example)) and optional `VECTOR_DB_DSN`; the client only needs to supply **URLs and credentials** (via `.env` or a secret store), not build PostgreSQL or pgvector from source.
- **KB in this repo:** [`email_automation/kb/store.py`](../email_automation/kb/store.py) stores vectors in PostgreSQL with **pgvector** (table `mailpilot_kb_chunks`). You must run `CREATE EXTENSION vector;` on the target database — see [kb-pgvector-setup.md](kb-pgvector-setup.md). If `VECTOR_DB_DSN` is empty, the app uses the **same** database as `DJANGO_DB_*`.

## Second option: Docker (`pgvector` image)

Suitable for **small deployments** or clients comfortable running **Docker**.

- Example in repo: [`docker-compose.yml`](../docker-compose.yml) and [`docker/postgres/init/01-init.sql`](../docker/postgres/init/01-init.sql) (`CREATE EXTENSION vector` on first init).
- The client must plan **volume backups**, **image updates**, and **host security** (not covered here).

**Caution:** `docker compose down -v` can delete named volumes; document backup procedures before any destructive command.

## Option to avoid for most client handovers

**Vanilla PostgreSQL on Windows/Linux + building/installing pgvector manually** on the app server. It often increases support load (version/OS mismatches, missing extension files, permission issues). The error `extension "vector" is not available` usually means the **server** does not have the pgvector extension installed.

## Environment variables (summary)

| Area | Variables | Notes |
|------|-----------|--------|
| Django app DB | `DJANGO_DB_*` | See [`.env.example`](../.env.example) |
| One-time Postgres bootstrap (optional) | `POSTGRES_BOOTSTRAP_USER`, `POSTGRES_BOOTSTRAP_PASSWORD` | Only if using [`postgres_bootstrap`](../core/management/commands/postgres_bootstrap.py) to align app user + DB |
| KB / vector | `VECTOR_DB_DSN` (optional) | **Empty** = same Postgres as `DJANGO_*`. Requires `vector` extension. |
| Embeddings | `LLM_API_KEY` / `OPENAI_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_DIM` | Real vectors need an API key; else zero vectors. |
| Security | `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false` in production | **Never** commit real `.env` to git (`.gitignore` should exclude it) |

## First deploy (high level)

1. Python 3.10+ and `pip install -r requirements.txt`
2. Copy `.env.example` → `.env` and set secrets and DB URLs
3. On the **application database** (or `VECTOR_DB_DSN` if set), run `CREATE EXTENSION vector;` — see [kb-pgvector-setup.md](kb-pgvector-setup.md).
4. `python manage.py migrate`
5. Use a production WSGI/ASGI server and HTTPS in front; set `ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` for your domain (see [Django deployment](https://docs.djangoproject.com/en/stable/howto/deployment/))

## Backups

- **Managed DB:** use the provider’s automated backups and test a restore in staging.
- **Self-hosted (Docker or VM):** schedule `pg_dump` (and encrypt off-site). Include Django tables and the `mailpilot_kb_chunks` table if KB is in use.

## Embeddings (KB)

- [`email_automation/kb/embedder.py`](../email_automation/kb/embedder.py) can call **OpenAI Embeddings** when `LLM_API_KEY` or `OPENAI_API_KEY` is set; otherwise **zero vectors** (poor for semantic search).

## Project-specific commands (reference)

| Command | Purpose |
|---------|---------|
| `python manage.py migrate` | Apply Django migrations |
| `python manage.py postgres_bootstrap` | (Optional) Create/align `DJANGO_DB_*` role and database using superuser credentials in `.env` |
| `python manage.py migrate_sqlite_state_store` | (Optional) One-time import from legacy `data/state.db` if migrating from an old layout |

## Support contact

Client operations should have access to: PostgreSQL admin, application `.env` / secret store, SSL certificates, and backup/restore runbooks.
