# MailPilot — Troubleshooting (Windows Server + Docker)

## 1) “database does not exist”

Example error:

- `FATAL: database "mailpilot" does not exist`

Fix:

- Confirm Docker DB is running: `docker compose ps`
- Confirm `.env` values match the DB:
  - `DJANGO_DB_NAME=mailpilot`
  - `DJANGO_DB_USER=mailpilot_user`
  - `DJANGO_DB_PASSWORD=...`
  - `DJANGO_DB_HOST=127.0.0.1`
  - `DJANGO_DB_PORT=<mapped host port>`
- If you changed compose port mapping (e.g. `5433:5432`), `DJANGO_DB_PORT` must be `5433`.

## 2) “extension vector is not available”

Meaning:
- You are connecting to a PostgreSQL server that does not have pgvector installed, or the role can’t create extensions.

Fix:
- Use the `pgvector/pgvector` Docker image (already in this repo’s `docker-compose.yml`)
- Enable extension once on the target database:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## 3) KB shows 0 docs / 0 chunks after JSON upload

Meaning:
- The uploaded JSON produced no usable document text, or the JSON shape wasn’t supported.

Fix:
- Confirm the upload response says non-zero chunks.
- Verify DB insert:

```sql
SELECT COUNT(*) FROM mailpilot_kb_chunks;
SELECT tenant_id, COUNT(*) FROM mailpilot_kb_chunks GROUP BY tenant_id;
```

## 4) Docker container name conflict (mailpilot-db)

Error:
- `Conflict. The container name "/mailpilot-db" is already in use`

Fix:
- Stop/remove the old container, or change `container_name` in `docker-compose.yml`.

## 5) “port is already allocated”

Meaning:
- Another process/service already uses port 5432 (or 8000).

Fix:
- Change host port mapping in `docker-compose.yml`, then match it in `.env`.

## 6) OAuth redirect mismatch

Fix:
- `OAUTH_REDIRECT_URI` must match the Google Console Authorized Redirect URI exactly (domain + path).

