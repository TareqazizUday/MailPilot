# MailPilot API Reference (Mobile / v1)

Base URL: `{API_BASE_URL}/api/v1`  
Auth header: `Authorization: Bearer <access_token>`  
Note: `APPEND_SLASH = False` — use paths exactly as listed (no trailing slash unless shown).

JWT: access ~30 minutes, refresh ~14 days (`ROTATE_REFRESH_TOKENS=True`).

Deep link for Gmail OAuth: `mailpilot://oauth/gmail`  
Set Django `OAUTH_REDIRECT_URI` to that value for mobile builds.

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
| GET | `/gmail/oauth/authorize-url` | `{ ok, authorization_url, state }` |
| POST | `/gmail/oauth/exchange` | `{ code, state? }` |
| GET | `/gmail/connection-status` | `?include_accounts=1&account_id=` |
| POST | `/gmail/disconnect` | optional `{ account_id }` |
| GET | `/gmail/inbox` | `{ ok, threads[], ... }` |
| GET | `/gmail/threads/<thread_id>` | `{ ok, messages[], ... }` |
| POST | `/trigger-poll` | start background poll |
| GET | `/pending` | queue items |

## Mail accounts (JWT)

| Method | Path |
|--------|------|
| GET | `/mail-accounts` |
| POST | `/mail-accounts/create` |
| GET/PATCH/DELETE | `/mail-accounts/<id>` |
| POST | `/mail-accounts/<id>/test-smtp` |
| POST | `/mail-accounts/<id>/disconnect-gmail` |
| POST | `/transport-mode` |

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

---

## Mobile env

```
EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:8000
EXPO_PUBLIC_WEB_BASE_URL=http://10.0.2.2:8000
```

- Android emulator → `10.0.2.2`
- iOS simulator → `127.0.0.1`
- Physical device → LAN IP of the Django host
