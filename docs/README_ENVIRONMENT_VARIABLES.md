# MailPilot — Environment variables (.env) reference

This project reads configuration from a `.env` file in the repository root (same folder as `manage.py`).

Copy `.env.example` → `.env` and fill values.

---

## Required for production

### Django

- `DJANGO_DEBUG=false`
- `DJANGO_SECRET_KEY=<generate a new secret>`
- `DJANGO_ALLOWED_HOSTS=<comma separated domains>`

### Database (Django app DB)

- `DJANGO_DB_ENGINE=django.db.backends.postgresql`
- `DJANGO_DB_HOST=127.0.0.1` (or DB host)
- `DJANGO_DB_PORT=5432` (or your mapped port)
- `DJANGO_DB_NAME=mailpilot`
- `DJANGO_DB_USER=mailpilot_user`
- `DJANGO_DB_PASSWORD=<strong password>`

### Knowledge Base / vectors (pgvector)

- `VECTOR_DB_DSN=` (optional)

If `VECTOR_DB_DSN` is empty, the KB uses the same DB as `DJANGO_DB_*`.

The DB must have:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### LLM / Embeddings (recommended)

Without an API key, embeddings can fall back to “zero vectors” (search quality will be poor).

- `LLM_API_KEY=<OpenAI key>` (preferred) OR `OPENAI_API_KEY=<OpenAI key>`
- `EMBEDDING_MODEL=text-embedding-3-small`
- `EMBEDDING_DIM=1536`
- `LLM_MODEL=gpt-4o-mini` (or client preference)

---

## Optional / depends on setup

### Gmail OAuth (recommended if using Gmail API)

- `GOOGLE_CLIENT_SECRET_FILE=client_secret.json`
- `GOOGLE_TOKEN_FILE=data/token.json`
- `OAUTH_REDIRECT_URI=https://<your-domain>/api/gmail/oauth/callback`

### SMTP / IMAP (if not using Gmail API)

- `SEND_TRANSPORT=smtp`
- SMTP settings: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, TLS flags
- IMAP settings: `IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`, TLS flags

---

## Security notes (must follow)

- Never send/commit the real `.env`.
- Rotate credentials at handover:
  - DB password
  - SMTP/IMAP password
  - OpenAI key
  - `DJANGO_SECRET_KEY`

