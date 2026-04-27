# MailPilot — Client Setup (Windows Server + Docker)

This guide is written for a **Windows Server** deployment where **PostgreSQL + pgvector runs in Docker**, and the MailPilot app runs on the server.

If you already have a working production instance (example: `https://mailpilot.tedbotai.com/`), you can still use this guide as the baseline runbook for a new client server.

---

## 0) What the client receives

- This repository (source code)
- A copy of `.env.example` (NOT a real `.env`)
- A deployment note with:
  - **Domain** (e.g. `mail.client.com`)
  - DNS ownership/contact
  - SSL/TLS approach (Let’s Encrypt or client certificate)
  - Support contacts

---

## 1) Install prerequisites (server)

- **Docker** + **Docker Compose**
  - Windows Server can run Docker in different ways depending on edition and policy.
  - The client’s ops team should pick the standard they support.
- **Python** 3.10+ and `pip`
- **Git** (optional but recommended)

---

## 2) Get the code on the server

Place the repo in a folder like:

- `C:\\apps\\mailpilot\\`

The folder must contain:

- `manage.py`
- `docker-compose.yml`
- `.env.example`

---

## 3) Start PostgreSQL (Docker, includes pgvector)

From the repo root (where `docker-compose.yml` exists):

```powershell
docker compose up -d
docker compose ps
```

### Port conflicts (important)

Default mapping is `5432:5432` (host:container). If port `5432` is already used on the server:

1) Edit `docker-compose.yml` and change:

- `"5432:5432"` → `"5433:5432"` (or another host port)

2) In `.env`, set:

- `DJANGO_DB_PORT=5433`

---

## 4) Create `.env` (server secrets)

Copy `.env.example` → `.env` in the repo root.

Minimum production values:

- **Django**
  - `DJANGO_DEBUG=false`
  - `DJANGO_SECRET_KEY=<generate-a-new-secret>`
  - `DJANGO_ALLOWED_HOSTS=<your-domain-or-ip>`
- **Database** (match `docker-compose.yml`)
  - `DJANGO_DB_ENGINE=django.db.backends.postgresql`
  - `DJANGO_DB_HOST=127.0.0.1`
  - `DJANGO_DB_PORT=5432` (or your mapped port)
  - `DJANGO_DB_NAME=mailpilot`
  - `DJANGO_DB_USER=mailpilot_user`
  - `DJANGO_DB_PASSWORD=<set-a-strong-password>`
- **KB vectors**
  - Leave `VECTOR_DB_DSN=` empty to use the same DB as `DJANGO_DB_*`
- **LLM / embeddings** (recommended for good KB search)
  - `LLM_API_KEY=<openai-key>` (or `OPENAI_API_KEY=...`)
  - `EMBEDDING_MODEL=text-embedding-3-small`
  - `EMBEDDING_DIM=1536`

Security rule: **never** commit `.env` to git.

---

## 5) Ensure pgvector is enabled

If the database volume is created fresh, `docker/postgres/init/01-init.sql` runs and enables `vector`.

If the DB already existed (old volume), run once in the `mailpilot` database:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Verification query:

```sql
SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector');
```

---

## 6) Install Python dependencies (server)

In the repo root:

```powershell
pip install -r requirements.txt
```

---

## 7) Run migrations (creates Django tables)

```powershell
python manage.py migrate
```

---

## 8) Start the app

### Basic (for internal/UAT)

```powershell
python manage.py runserver 0.0.0.0:8000
```

### Production (recommended)

Use a real process manager + reverse proxy + HTTPS.

Common Windows patterns:

- Run the app as a **Windows Service** (NSSM / Service Wrapper)
- Put **IIS (ARR)** or **Nginx** in front for HTTPS + domain routing

If the client wants a fully dockerized app container too, add a Dockerfile + app service in compose (not included in this repo by default).

---

## 9) Post-deploy checks (must pass)

- App loads in browser at your domain
- Login works
- KB status is OK:
  - open `/setup` → Knowledge Base → upload JSON → ingest
  - DB confirms rows:

```sql
SELECT COUNT(*) FROM mailpilot_kb_chunks;
```

---

## 10) Backups (must set up)

See: `docs/README_BACKUPS.md`

---

## 11) Troubleshooting

See: `docs/README_TROUBLESHOOTING.md`

