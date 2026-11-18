# Staging checklist — Gmail + Microsoft mailbox OAuth

Use after configuring env per [OAUTH_MAILBOX_CONNECT.md](OAUTH_MAILBOX_CONNECT.md).

## Automated

```bash
python manage.py test core.tests_oauth_mailbox
```

## Manual

1. **Gmail one-click**
   - Ensure `GOOGLE_CLIENT_SECRET_FILE` points to a valid Web client JSON.
   - Setup → Gmail → Add Gmail account → **Connect with Google** → consent → return to Setup with Active status.
   - Dashboard inbox loads; trigger poll once.
2. **Gmail Advanced BYO**
   - Upload a different `credentials.json` under Advanced; reconnect works.
3. **Microsoft**
   - Set `MICROSOFT_OAUTH_*` env; restart.
   - Setup → Microsoft → Add → **Connect with Microsoft** → consent → Active.
   - Switch transport mode to Microsoft; poll once.
4. **Disconnect / reconnect** both providers.
5. **Plan limits** — Starter single inbox still blocks a second enabled mailbox across transports.
6. **SMTP** tab still create / test / poll as before.
