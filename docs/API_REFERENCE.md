# MailPilot API Reference (Mobile / v1)

Base URL: `{API_BASE_URL}/api/v1`  
Auth header: `Authorization: Bearer <access_token>`  
Note: `APPEND_SLASH = False` — use paths exactly as listed (no trailing slash unless shown).

JWT: access ~30 minutes, refresh ~14 days (`ROTATE_REFRESH_TOKENS=True`).

Gmail OAuth for the app: keep `OAUTH_REDIRECT_URI` (Google Console redirect URI) on the **website** callback `{SITE_URL}/api/gmail/oauth/callback`. The app passes its deep link (e.g. `mailpilot://oauth/gmail`) as `return_to` — see [Gmail mobile connect](#gmail-mobile-connect).

---

## Auth (public)

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/auth/token` | `{ "username", "password" }` — username **or email** | `{ "access", "refresh" }` |
| POST | `/auth/refresh` | `{ "refresh" }` | `{ "access", "refresh"? }` |
| POST | `/auth/signup` | `{ first_name, last_name, email, password, password2, terms, username? }` | `{ ok, user, access, refresh }` |
| POST | `/auth/password-reset/request` | `{ "identifier" }` | `{ ok, email, email_hint }` |
| POST | `/auth/password-reset/verify` | `{ "email", "otp" }` | `{ ok, reset_token }` |
| POST | `/auth/password-reset/confirm` | `{ "reset_token", "password", "password2" }` | `{ ok }` |
| GET | `/auth/social/providers` | — | `{ ok, providers: [{ id, label, configured }] }` |
| GET | `/auth/social/<provider>/authorize-url` | `?return_to=<deep link>` | `{ ok, authorization_url, state }` |
| POST | `/auth/social/exchange` | `{ "code" }` | `{ ok, created, user, access, refresh }` |
| POST | `/auth/social/token` | `{ provider, id_token? , access_token? }` | `{ ok, created, user, access, refresh }` |

### Social login (Google / GitHub)

The website buttons and the app use the same provider keys and the same account rule: a **verified email** signs in to the existing account with that email (case-insensitive), otherwise a new account is created (Starter plan, no password — the user can set one via password reset). `created` tells the app which happened.

**Firebase in-app browser flow (Google in Expo Go, GitHub always)**

Open `{SITE_URL}/auth/social/firebase/app?provider=<google|github>&return_to=<app link>` with `WebBrowser.openAuthSessionAsync`. The page runs the Firebase popup and redirects to `return_to?status=ok&code=<one-time>&provider=<id>` (or `status=error&error=<code>`); redeem the code with `POST /auth/social/exchange` (step 4 below).

**Google redirect flow (without Firebase)**

1. `GET /auth/social/providers` — hide buttons with `configured: false` (`github` needs the Firebase web config).
2. `GET /auth/social/google/authorize-url?return_to=mailpilot://auth/social` → open `authorization_url` in the system browser (e.g. `WebBrowser.openAuthSessionAsync`).  
   `return_to` rules are the same as Gmail connect (`mailpilot://`, `exp://`, `exps://`, `http://localhost:8081`, `http://127.0.0.1:8081`, `SITE_URL`).
3. The provider returns to the website callback, which redirects to  
   `return_to?status=ok&code=<one-time>&provider=<id>` or `return_to?status=error&error=<code>&provider=<id>` (state valid 10 minutes).
4. `POST /auth/social/exchange { "code" }` within **2 minutes** → JWT. The code works once.

**Native SDK flow (optional)**

- Google Sign-In: `POST /auth/social/token { "provider": "google", "id_token": "..." }`. The token audience must be `GOOGLE_LOGIN_CLIENT_ID` or one of `GOOGLE_LOGIN_MOBILE_CLIENT_IDS`.
- Firebase Auth: `POST /auth/social/token { "provider": "firebase", "id_token": "<Firebase ID token>", "access_token": "<GitHub OAuth token, GitHub only>" }`. Verified against `FIREBASE_PROJECT_ID`; only `sign_in_provider` `google.com` and `github.com` are accepted (`400 unsupported_sign_in_provider` otherwise). For GitHub the server reads the verified (primary) email from the GitHub API with `access_token` (popup scope `user:email`) and checks the GitHub user id matches the Firebase token. Same email → same account as web login.

**Error codes** (`{ ok:false, error }`, or `error` in the deep link)

| Code | HTTP | Meaning |
|------|------|---------|
| `unknown_provider` | 404 | Redirect flow: not `google`; native: not `firebase` or `google` |
| `not_configured` | 503 | Server has no keys for that provider |
| `invalid_return_to` | 400 | `return_to` not an allowed app link |
| `invalid_or_expired_code` | 400 | Exchange code unknown, used or older than 2 minutes |
| `invalid_token` | 401 | Native token invalid or issued for another app |
| `id_token_required` / `access_token_required` | 400 | Wrong native payload (GitHub needs `access_token`) |
| `unsupported_sign_in_provider` | 400 | Firebase token from a provider other than Google/GitHub |
| `inactive` | 403 | Account disabled |
| `cancelled`, `state_mismatch`, `email_missing`, `email_unverified`, `failed` | deep link | Browser flow outcome |

Google redirect URI (shared by web and app): `{SITE_URL}/auth/social/google/callback`. GitHub OAuth App callback: `https://<firebase-project>.firebaseapp.com/__/auth/handler`.

## Profile (JWT)

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/me` | — | `{ ok, user }` |
| PATCH | `/me` | profile fields | `{ ok, user }` |
| POST | `/me/change-password` | `{ current_password, new_password }` | `{ ok }` |
| POST | `/me/avatar` | multipart `avatar` (PNG/JPG/WEBP/GIF, max 2 MB) | `{ ok, user }` |
| DELETE | `/me/avatar` | — | `{ ok, user }` |

`user` shape: `id, username, email, first_name, last_name, display_name, phone, company, timezone, notes, avatar_url`. `avatar_url` is an absolute URL, or `null` when no photo is set.

## Gmail / Inbox (JWT)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/gmail/oauth/authorize-url` | `?account_id=&return_to=` → `{ ok, authorization_url, state }` |
| POST | `/gmail/oauth/exchange` | `{ code, state?, account_id? }` → `{ ok, account_id? }` (fallback; the callback already saves the token) |
| GET | `/gmail/connection-status` | `?include_accounts=1&account_id=` |
| POST | `/gmail/disconnect` | optional `{ account_id }` |
| GET | `/gmail/inbox` | `{ ok, threads[], ... }` |
| GET | `/gmail/threads/<thread_id>` | `{ ok, messages[], ... }` |
| POST | `/trigger-poll` | start background poll |
| GET | `/pending` | queue items |

### Gmail mobile connect

1. `POST /mail-accounts/create` `{ "transport": "gmail_api" }` (or reuse an existing Gmail mailbox id).
2. `POST /mail-accounts/<id>/setup-credentials` — multipart `gmail_address` + `client_secret` (`.json` from Google Cloud) → `{ ok, account }`.  
   Errors: `404 not_found` (missing / not a Gmail mailbox), `400` (missing field, not `.json`, invalid JSON).
3. `GET /gmail/oauth/authorize-url?account_id=<id>&return_to=<deep link>` → open `authorization_url` in the system browser.  
   `return_to` must start with `mailpilot://`, `exp://`, `exps://`, `http://localhost:8081`, `http://127.0.0.1:8081` or `SITE_URL`; otherwise `400 invalid_return_to`. `400 client_secret_missing` if step 2 was skipped.
4. Google returns to the website callback, which saves the token **on that mailbox** and redirects to  
   `return_to?status=ok&account_id=<id>` or `return_to?status=error&error=<reason>` (state valid for 10 minutes).
5. Refresh with `GET /mail-accounts/<id>` or `/gmail/connection-status?account_id=<id>`.

`POST /setup/credentials` (same multipart fields, first Gmail mailbox) also returns `{ ok, account }`. When the user has no Gmail mailbox yet and the plan has no free slot it returns `403 { ok:false, error:"plan_inbox_limit_reached", upgrade_required:true, billing }` — same as `/mail-accounts/create`.

## Dashboard (JWT)

| Method | Path | Query | Response |
|--------|------|-------|----------|
| GET | `/dashboard/summary` | `days=1..31` (optional, default 7) | see below |

One call returns everything the Dashboard tab needs, computed on the server across **all** mailboxes (the website `/dashboard` uses the same data). Prefer it over combining `/pending` + `/mail-accounts` + `/billing/summary`: `/pending` only returns the last 20 queue items of one mailbox, so totals built from it are wrong once a user has more mail.

```json
{
  "ok": true,
  "generated_at": "2026-10-11T11:30:00+00:00",
  "timezone": "Asia/Dhaka",
  "window_days": 7,
  "plan": { "code": "starter", "label": "Starter plan", "starter_expired": false },
  "mailboxes": {
    "connected": 1, "total": 2,
    "items": [
      { "id": 5, "slot": 1, "transport": "gmail_api|smtp", "label": "support@acme.com", "email": "support@acme.com",
        "is_enabled": true, "inbox_ready": true, "status": "ok|needs_setup|oauth_mismatch|disabled",
        "processed": 42, "last_processed_at": "2026-10-11T10:58:00+00:00" }
    ]
  },
  "totals": { "processed": 42, "sent": 30, "drafts": 4, "filtered": 7, "failed": 1, "pending": 0,
              "latest_processed_at": "2026-10-11T10:58:00+00:00" },
  "breakdown": [ { "key": "sent", "label": "Sent", "count": 30, "percent": 71 }, "... drafts, filtered, failed" ],
  "daily": [ { "date": "2026-10-05", "label": "Mon", "auto_replied": 3, "other": 1, "total": 4 }, "... 7 items, oldest first, last = today" ],
  "week_total": 19,
  "recent": [
    { "action": "sent|draft|ignored|error", "label": "Sent", "subject": "...", "from_email": "...", "reason": "auto_reply",
      "processed_at": "...", "thread_id": "...", "message_id": "...", "account_id": 5, "account_label": "support@acme.com" }
  ],
  "usage": { "...": "same object as /billing/summary -> billing" }
}
```

Rendering notes for the app:
- Hero: `Mailboxes` = `connected/total`, `Processed` = `totals.processed`, `Latest` = `totals.latest_processed_at` (format as relative time).
- `daily` is bucketed in the user's profile timezone (`timezone`); `auto_replied` = sent, `other` = drafts + filtered + failed.
- Open a `recent` item in the Inbox with `account_id` + `thread_id`.
- Timestamps are ISO-8601 UTC; `latest_processed_at` / `last_processed_at` are `null` when nothing has been processed.

## Mail accounts (JWT)

| Method | Path | Response |
|--------|------|----------|
| GET | `/mail-accounts` | `{ ok, accounts[], summary }` |
| POST | `/mail-accounts/create` | `{ ok, account }` |
| GET/PATCH | `/mail-accounts/<id>` | `{ ok, account }` |
| DELETE | `/mail-accounts/<id>` | `{ ok }` |
| POST | `/mail-accounts/<id>/setup-credentials` | `{ ok, account }` (Gmail only, multipart) |
| POST | `/mail-accounts/<id>/test-smtp` | `{ ok, sent_to }` |
| POST | `/mail-accounts/<id>/disconnect-gmail` | `{ ok }` |
| POST | `/transport-mode` | `{ ok, summary }` |

## Knowledge base / config / SMTP (JWT)

See existing routes: `/kb/*`, `/admin/config`, `/smtp/test`, `/smtp/status`, `/smtp/disconnect`.

## Pricing (public, JWT optional)

Same plans, prices, and copy as the website `#pricing` section — edit them in Admin → Website → Pricing and the app picks up the change on the next request (no app release needed).

| Method | Path | Query | Response |
|--------|------|-------|----------|
| GET | `/pricing` | `currency=usd\|gbp\|eur` (optional), `interval=monthly\|yearly` (optional) | see below |

- Without `currency`, the server uses the same rule as the website (UK or unknown → GBP, Eurozone → EUR, elsewhere → USD).
- Send the `Authorization` header when signed in to get `account` state, `is_current`, and logged-in button labels. An invalid/expired token is ignored (the public feed still returns).
- Only plans that are **published** and **shown on homepage** are returned, in admin sort order.

```json
{
  "ok": true,
  "currency": "gbp", "currency_label": "GBP", "currency_symbol": "£",
  "available_currencies": [{ "code": "usd", "label": "USD", "symbol": "$" }, "..."],
  "billing_interval": "monthly",
  "header": { "tag": "Pricing", "title_lead": "Simple plans for", "title_highlight": "every inbox size", "intro": "..." },
  "plans": [
    {
      "code": "pro", "tier_label": "Pro", "top_badge": "50% launch offer",
      "ribbon": { "type": "free|soon", "label": "...", "icon_class": "fa-solid fa-bolt" } ,
      "description": "...",
      "features": ["1,000 tokens per month ..."],
      "features_html": ["1,000 tokens per month ..."],
      "is_featured": true, "is_current": false, "sort_order": 2,
      "monthly": { "price": "£16", "suffix": "/mo", "was": "£32", "save_label": "Save 50%", "period": "Billed monthly · cancel anytime" },
      "yearly":  { "price": "£160", "suffix": "/yr", "was": "£320", "save_label": "Save 50%", "period": "Billed annually · cancel anytime" },
      "currencies": { "usd": { "monthly": {}, "yearly": {} }, "gbp": {}, "eur": {} },
      "cta": { "label": "Get Pro", "style": "primary|secondary", "action": "checkout_pro", "url": "https://.../billing/checkout/pro" }
    }
  ],
  "account": { "authenticated": true, "current_plan": "starter", "starter_expired": false },
  "updated_at": "2026-10-08T12:00:00+00:00"
}
```

Rendering notes for the app:
- Show `monthly` or `yearly` based on the toggle; switch currency locally with `currencies[code]` (no extra request).
- `price` is empty for plans without a fixed price (Starter free tier, Custom builder) — show `period` instead, like the website.
- `features` is plain text; `features_html` keeps `<strong>` etc. if you render rich text.
- `ribbon` is `null` when the card has no badge. `top_badge` is an empty string when unset.
- `cta.action`: `login`, `signup`, `profile`, `upgrade`, `checkout_pro`, `custom_builder`. Payments stay on the website — open `cta.url` in an in-app browser (or call `/billing/select-plan` first for signed-in users).
- Use `updated_at` to cache and skip re-rendering when nothing changed.

## Billing (JWT)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/billing/summary` | plan, tokens, trial |
| POST | `/billing/select-plan` | `{ plan, billing_interval? }` → may include `redirect` for web checkout |

Open `redirect` (or `/pricing`) in an in-app browser; Stripe/PayPal stay on the website.

## Integrations (JWT)

| Method | Path |
|--------|------|
| GET/POST | `/telegram/status`, `/telegram/config`, `/telegram/test` |
| GET/POST | `/whatsapp/status`, `/whatsapp/config`, `/whatsapp/test` |

## Notifications (JWT, or session + CSRF on the web)

Every draft / sent / error event is stored once and shown in the bell (web) and the app. It is also sent as an Expo push to registered devices. Telegram / WhatsApp follow `external_mode`: `fallback` (default) only sends them when the user has no working push device **and** has not been active on web/app in the last `NOTIFY_FALLBACK_ONLINE_SECONDS` (120).

| Method | Path | Notes |
|--------|------|-------|
| GET | `/notifications?unread=1&cursor=&limit=` | `{ items, next_cursor, unread_count }`, newest first, `limit` max 100 |
| GET | `/notifications/unread-count` | `{ unread_count, latest }`. Poll target; also marks the user active |
| POST | `/notifications/<id>/read` | 404 if not yours |
| POST | `/notifications/read-all` | `{ updated }` |
| GET/PUT/PATCH | `/notifications/preferences` | partial: `in_app`, `push`, `external_mode` (`off`/`always`/`fallback`), `events {draft,sent,error}`, `quiet_hours {enabled,start,end}` (`HH:MM`, profile time zone) |
| POST | `/devices/register` | `{ expo_token, platform: ios/android, device_name? }`. Re-registering the same token is safe |
| POST | `/devices/unregister` | `{ expo_token }`. Call **before** clearing the JWT on logout |

Item shape: `{ id, event, title, body, data, account_id, read, read_at, created_at }`. `data.deep_link` is `mailpilot://thread/<thread_id>` (Gmail) or `mailpilot://notifications`; push payloads carry the same `data` plus `notification_id`.

### Expo client checklist

1. `npx expo install expo-notifications expo-device expo-constants`, add the `expo-notifications` plugin to `app.json`, upload the FCM V1 key with `eas credentials`, then make a new build (remote push does not work in Expo Go on Android).
2. After login and on app start: request permission, `getExpoPushTokenAsync({ projectId })`, `POST /devices/register`.
3. On logout: `POST /devices/unregister`, then clear tokens.
4. Handle taps with `addNotificationResponseReceivedListener` and `getLastNotificationResponseAsync`, opening `data.deep_link`.
5. Optional: a notifications screen on `GET /notifications`, a badge from `/notifications/unread-count` (refresh on `AppState` foreground), and a settings screen on `/notifications/preferences`.

---

## Mobile env

```
EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:8000
EXPO_PUBLIC_WEB_BASE_URL=http://10.0.2.2:8000
```

Server env for push: `EXPO_ACCESS_TOKEN` (optional, only if "enhanced push security" is on in Expo), `NOTIFY_FALLBACK_ONLINE_SECONDS`, `NOTIFY_EXTERNAL_RATE_LIMIT` (per minute, default 10, extras are sent as one digest), `NOTIFY_RETENTION_DAYS` (default 90).

- Android emulator → `10.0.2.2`
- iOS simulator → `127.0.0.1`
- Physical device → LAN IP of the Django host
