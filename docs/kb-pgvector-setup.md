# Enable pgvector for MailPilot KB

The knowledge base stores embeddings in PostgreSQL using the **pgvector** extension (`vector` type).

## Option A: Docker (good if Windows native PostgreSQL has no `vector` files)

The repo includes [`docker-compose.yml`](../docker-compose.yml) using the official **`pgvector/pgvector:pg16`** image — the extension is already inside the image.

### 1) Prerequisites

- [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/) installed and running (WSL2 backend recommended).

### 2) Port 5432 conflict

- If **local PostgreSQL** (e.g. PostgreSQL 18) is already using **port 5432**, either **stop** that service (Windows Services → PostgreSQL) **or** change the host port in `docker-compose.yml` from `5432:5432` to e.g. `5433:5432` and set `DJANGO_DB_PORT=5433` in `.env`.

### 3) Start the database

From the **project root** (folder that contains `docker-compose.yml`):

```bash
docker compose up -d
```

Check logs:

```bash
docker compose logs -f db
```

### 4) What you get (defaults in `docker-compose.yml`)

| Variable | Value |
|----------|--------|
| Host (from your PC) | `127.0.0.1` |
| Port | `5432` (or the host port you mapped) |
| Database | `mailpilot` |
| User | `mailpilot_user` |
| Password | `mailpilot_password` (change in compose for production) |

The init script [`docker/postgres/init/01-init.sql`](../docker/postgres/init/01-init.sql) runs **only on first create** of an empty data volume and runs `CREATE EXTENSION vector;`.

### 5) Point MailPilot at this database

In **`.env`** (align with the compose file or your chosen password):

```env
DJANGO_DB_ENGINE=django.db.backends.postgresql
DJANGO_DB_NAME=mailpilot
DJANGO_DB_USER=mailpilot_user
DJANGO_DB_PASSWORD=mailpilot_password
DJANGO_DB_HOST=127.0.0.1
DJANGO_DB_PORT=5432
# KB same DB (optional):
VECTOR_DB_DSN=
```

Then from the project root (with your Python venv):

```bash
python manage.py migrate
```

You do **not** need to run `CREATE EXTENSION vector` by hand in pgAdmin for this container — the init script does it on first init. The app’s `VectorStore` also runs `CREATE EXTENSION IF NOT EXISTS` when connecting (if your role can).

### 6) Stopping / data

- `docker compose stop` — stop containers; data stays in the named volume `mailpilot_pg_data`.
- **`docker compose down -v`** — **deletes** the volume and all DB data. Avoid in production without backup.

### 7) Native PostgreSQL and Docker at the same time

Use **different ports** (e.g. native on 5432, Docker on 5433) so they do not fight for the same port.

---

## 1) Install `vector` in your database (once per database) — **native** PostgreSQL

Connect as a superuser (e.g. `postgres`) to the same database the app uses (`DJANGO_DB_NAME`), then:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

If the extension files are not installed on the server, you will get `extension "vector" is not available`. In that case install the **pgvector** package for your OS/PostgreSQL version, or use a host image that includes it (e.g. Docker `pgvector/pgvector` — see [docker-compose.yml](../docker-compose.yml) in this repo).

## 2) App user permissions (optional)

If the app user **cannot** run `CREATE EXTENSION`, run the `CREATE EXTENSION` step as superuser once; the app can still `CREATE TABLE` for `mailpilot_kb_chunks` if it has `CREATE` on the schema (usually `public`).

## 3) Application configuration

- **Same database as Django (typical):** leave `VECTOR_DB_DSN` empty; KB uses `DJANGO_DB_HOST`, `DJANGO_DB_NAME`, `DJANGO_DB_USER`, `DJANGO_DB_PASSWORD` from `.env`.
- **Separate database:** set `VECTOR_DB_DSN` to a `postgresql://...` URL (must also have the `vector` extension enabled).

## 4) Real embeddings (recommended for search quality)

Set `LLM_API_KEY` or `OPENAI_API_KEY`, and set `EMBEDDING_MODEL` to an OpenAI embedding model. Match `EMBEDDING_DIM` to that model (e.g. 1536 for `text-embedding-3-small`).

Without an API key, the embedder falls back to **zero vectors** (not good for semantic similarity).

## 5) Verify

- `GET /api/kb/status` (authenticated) should return `configured: true` and document/chunk counts after ingest.
- If you see errors about `vector` type, re-check step 1.
