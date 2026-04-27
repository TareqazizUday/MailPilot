# MailPilot — Backups & Restore (Docker Postgres)

This runbook covers backups when PostgreSQL is running in Docker via `docker-compose.yml`.

MailPilot data is stored in:

- Django tables (users, settings, queue, logs)
- KB vectors table: `mailpilot_kb_chunks`

Both are in the same database by default (`mailpilot`).

---

## Backup strategy (recommended)

Use **logical backups** (`pg_dump`) on a schedule and store them **off the server** (encrypted).

### What to back up

- Full database: `mailpilot`
- (If you use a separate vector DB via `VECTOR_DB_DSN`, back that DB too)

---

## How to create a backup (PowerShell)

1) Identify the running container name (default is `mailpilot-db`):

```powershell
docker ps
```

2) Run `pg_dump` inside the container and write to a host file:

```powershell
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
docker exec mailpilot-db pg_dump -U mailpilot_user -d mailpilot -Fc > "C:\backups\mailpilot-$ts.dump"
```

Notes:
- `-Fc` creates a custom-format dump (good for restore).
- Ensure `C:\backups\` exists and is protected.

---

## How to restore (high-level)

Restores are destructive. Always test in staging first.

Example steps:

1) Create a fresh empty database (or drop/recreate)
2) Restore using `pg_restore`

Inside the container:

```powershell
docker cp "C:\backups\mailpilot-YYYYMMDD-HHMMSS.dump" mailpilot-db:/tmp/mailpilot.dump
docker exec mailpilot-db pg_restore -U mailpilot_user -d mailpilot --clean --if-exists /tmp/mailpilot.dump
```

Then run:

```powershell
python manage.py migrate
```

---

## Warning: Docker volume deletion

- `docker compose down -v` will delete the named volume (DB data loss).

---

## Verification queries

```sql
SELECT COUNT(*) FROM auth_user;
SELECT COUNT(*) FROM mailpilot_kb_chunks;
```

