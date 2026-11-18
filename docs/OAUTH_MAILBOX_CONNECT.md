# Automatic Gmail + Microsoft mailbox OAuth (Setup)

End users connect inboxes from **Setup** without uploading their own OAuth client JSON (when the server is configured).

## Gmail (shared app client)

1. Google Cloud → enable **Gmail API**.
2. OAuth consent screen (External). For public users, complete verification for restricted Gmail scopes.
3. Credentials → **OAuth client ID** → **Web application**.
4. Authorized redirect URIs:
   - `https://<your-domain>/api/gmail/oauth/callback`
   - Local: `http://127.0.0.1:8000/api/gmail/oauth/callback` (or your port)
5. Prefer putting the Web client credentials in `.env` (no JSON file on disk):

```env
GOOGLE_OAUTH_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxx
OAUTH_REDIRECT_URI=https://<your-domain>/api/gmail/oauth/callback
```

Optional fallback: download the client JSON and set `GOOGLE_CLIENT_SECRET_FILE=client_secret.json`.

6. Restart the app. Setup → Gmail → **Connect with Google**.

If Google returns **`invalid_client`**, rotate the secret in Google Cloud Console and update `GOOGLE_OAUTH_CLIENT_SECRET` in `.env` (staff Setup paste only updates a JSON file if one exists).

Setup primary CTA: **Connect with Google**. Optional **Advanced** disclosure lets a mailbox use its own uploaded `credentials.json` (BYO).

Scopes: `gmail.readonly`, `gmail.send`, `gmail.compose`, `gmail.modify`.

## Microsoft Graph

1. [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID** → **App registrations** → **New registration**.
2. Name: `Mailpilots` (or your brand).
3. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts** (`common`).
4. Redirect URI platform: **Web**
   - Local: `http://127.0.0.1:8000/api/microsoft/oauth/callback`
   - Production: `https://<your-domain>/api/microsoft/oauth/callback`
5. After create → **Certificates & secrets** → **New client secret** → copy the **Value** once.
6. **API permissions** → **Microsoft Graph** → **Delegated**:
   - `Mail.ReadWrite`
   - `Mail.Send`
   - `User.Read`
   - (`offline_access` is requested by the app during OAuth; add if you prefer it listed)
7. Grant admin consent if your org tenant requires it (personal Outlook/Hotmail usually does not).
8. Copy **Application (client) ID** into `.env`:

```env
MICROSOFT_OAUTH_CLIENT_ID=<Application client ID>
MICROSOFT_OAUTH_CLIENT_SECRET=<secret Value>
MICROSOFT_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/api/microsoft/oauth/callback
MICROSOFT_OAUTH_TENANT=common
```

9. Restart the app. Setup → **Microsoft** tab → **Add Microsoft account** → **Connect with Microsoft**.
10. Sign in with Outlook / Microsoft 365 → Allow. Dashboard inbox should list Graph mail.

Tokens are stored encrypted on `MailAccount.oauth_token_enc` (same field as Gmail) and mirrored to the per-account token file under `data/users/.../accounts/.../token.json`.

### Common Microsoft errors

| Symptom | Fix |
|--------|-----|
| Setup shows “Microsoft OAuth is not configured” | Fill `MICROSOFT_OAUTH_CLIENT_ID` + `SECRET`, restart |
| `AADSTS50011` / redirect mismatch | Azure Web redirect URI must **exactly** match `MICROSOFT_OAUTH_REDIRECT_URI` |
| `AADSTS700016` / app not found | Wrong client ID or deleted app registration |
| Connect works but Dashboard empty | Ensure active mode is **Microsoft** (Microsoft tab) and poll worker is running |
| Personal MSA blocked | App registration must allow personal Microsoft accounts (`common`) |

## Staging checklist

- [ ] Shared Google client present → Connect with Google completes and Dashboard shows inbox.
- [ ] Microsoft env set → Connect with Microsoft completes and poll runs in Microsoft mode.
- [ ] Disconnect clears token; reconnect works.
- [ ] Plan inbox limits still apply across Gmail / Microsoft / SMTP.
- [ ] SMTP tab still works for custom domains.

## Notes

- Gmail / Microsoft / SMTP **modes are mutually exclusive** (active transport mode).
- Google **login** (`GOOGLE_LOGIN_*` / Firebase) is separate from mailbox OAuth.
