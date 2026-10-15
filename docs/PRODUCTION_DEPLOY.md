# Production deploy গাইড (https://mailpilots.net)

একই কোড লোকাল আর লাইভ দুই জায়গায় চলে। কোন মেশিন কী, সেটা ঠিক হয় সেই মেশিনের `.env`-এর একটা লাইন দিয়ে:

| মেশিন | `.env` | ফলাফল |
|---|---|---|
| তোমার ল্যাপটপ | `MAILPILOT_ENV=local` | DEBUG চালু, HTTP, যেকোনো host (LAN IP / Expo Go) |
| লাইভ সার্ভার | `MAILPILOT_ENV=production` + `SITE_URL=https://mailpilots.net` | DEBUG বন্ধ, HTTPS redirect, secure cookie, শুধু mailpilots.net / www |

`.env` git-এ যায় না, তাই কোড কপি বা pull করলে লাইভের `.env` বদলায় না। লাইভে `SITE_URL` বা শক্ত `DJANGO_SECRET_KEY` না থাকলে অ্যাপ চালুই হবে না, পরিষ্কার error দেখাবে। ভুল সেটিং নিয়ে চুপচাপ চলবে না।

---

## ১. Deploy-এর আগে (একবার)

1. **লাইভ database-এর backup নাও** ([README_BACKUPS.md](README_BACKUPS.md)):
   ```bash
   pg_dump -U mailpilot_user -h 127.0.0.1 -p 5432 -Fc mailpilot > mailpilot_before_deploy.dump
   ```
2. লাইভ সার্ভারের এখনকার `.env`-এর একটা কপি রেখে দাও।

## ২. লাইভ সার্ভারের `.env`

[.env.production.example](../.env.production.example) দেখে লাইভের `.env`-এ এগুলো থাকা নিশ্চিত করো:

```env
MAILPILOT_ENV=production
SITE_URL=https://mailpilots.net
OAUTH_REDIRECT_URI=https://mailpilots.net/api/gmail/oauth/callback
DJANGO_SECURE_HSTS_SECONDS=0

FIREBASE_PROJECT_ID=mailpilot-f4add
FIREBASE_API_KEY=...
FIREBASE_AUTH_DOMAIN=mailpilot-f4add.firebaseapp.com
FIREBASE_APP_ID=...
```

**সাবধান:**
- লাইভের বর্তমান `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY` আর `DJANGO_DB_*` **বদলাবে না**। নতুন `FIELD_ENCRYPTION_KEY` দিলে সেভ করা mailbox password আর API key আর পড়া যাবে না।
- লোকালের `.env` লাইভে কপি করবে না। লোকালে `MAILPILOT_ENV=local`, test key আর লোকাল DB আছে।
- পুরনো `DJANGO_DEBUG`, `DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_COOKIE_SECURE` লাইন থাকলেও সমস্যা নেই, ওগুলোই আগে মানা হয়। না থাকলে production-এর নিরাপদ default চলে।
- `DJANGO_ALLOWED_HOSTS` আর `DJANGO_CSRF_TRUSTED_ORIGINS`-এ mailpilots.net আলাদা করে লিখতে হবে না, `SITE_URL` থেকে নিজে যোগ হয় (www সহ)।

## ৩. নতুন কোড সার্ভারে পাঠাও

git থাকলে সার্ভারে `git pull`। না থাকলে ফাইল কপি করো, কিন্তু এগুলো **কপি করবে না, সার্ভারের গুলোই রাখবে**:

- `.env`
- `client_secret.json`
- `data/` (ইউজারদের mailbox token)
- `media/` (avatar, marketing ছবি)
- `.venv/`
- `staticfiles/` (deploy স্ক্রিপ্ট নিজে বানায়)

## ৪. Deploy চালাও

**Windows সার্ভার (IIS + Waitress, port 8011):**
```powershell
cd <MailPilot ফোল্ডার>
powershell -ExecutionPolicy Bypass -File .\deploy_production.ps1
```
স্ক্রিপ্টটা ক্রমে যা করে:
1. `.env`-এ `MAILPILOT_ENV=production` আছে কিনা দেখে
2. `pip install -r requirements.txt`
3. `migrate` (নতুন notification টেবিল সহ)
4. `collectstatic`
5. `deploy_check`
6. Waitress রিস্টার্ট ([restart_8011.ps1](../restart_8011.ps1))

PayPal live ব্যবহার না করলে `-SkipBilling` দাও। শুধু প্রস্তুত করে নিজে রিস্টার্ট করতে চাইলে `-NoRestart`।

**Linux / অন্য সার্ভার:** একই কাজ হাতে:
```bash
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py deploy_check          # FAIL থাকলে থামো
sudo systemctl restart mailpilot       # তোমার সার্ভিসের নাম
```

`deploy_check` নিজেও যেকোনো সময় চালানো যায়: `python manage.py deploy_check`। OK, WARN আর FAIL তালিকা দেখায়। FAIL থাকলে লাইভে যাওয়ার আগে ঠিক করো।

## ৫. nginx / proxy

mailpilots.net nginx-এর পেছনে চলে। proxy-কে এই header-গুলো পাঠাতে হবে, না হলে redirect loop বা `400 Bad Request` হবে:

```nginx
location / {
    proxy_pass http://127.0.0.1:8011;
    proxy_set_header Host              $host;
    proxy_set_header X-Forwarded-Host  $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    client_max_body_size 50m;
}
```

nginx আগে থেকেই HSTS header পাঠায়, তাই Django-তে `DJANGO_SECURE_HSTS_SECONDS=0` রাখো। না হলে header দুবার যাবে। এজন্য `check --deploy`-এ `security.W004` warning আসবে, ওটা স্বাভাবিক। proxy যদি `X-Forwarded-Proto` পাঠাতে না পারে (যেমন IIS-এ server variable বন্ধ থাকলে), `.env`-এ দাও `DJANGO_BEHIND_HTTPS_PROXY=true`।

## ৬. বাইরের কনসোলে লাইভ ঠিকানা যোগ করো

| কোথায় | কী যোগ করবে |
|---|---|
| Firebase → Authentication → Settings → Authorized domains | `mailpilots.net`, `www.mailpilots.net` |
| Google Cloud → Credentials → Gmail OAuth client → Authorized redirect URIs | `https://mailpilots.net/api/gmail/oauth/callback` |
| Google Cloud → Google login client → Authorized redirect URIs (redirect fallback) | `https://mailpilots.net/auth/social/google/callback` |
| Google Cloud → OAuth consent screen | App domain = mailpilots.net, Privacy/Terms লিংক, **Publish app** |
| GitHub → Developer settings → OAuth Apps → MailPilot | Homepage URL = `https://mailpilots.net` (callback আগের মতোই `https://mailpilot-f4add.firebaseapp.com/__/auth/handler`) |
| Stripe Dashboard → Webhooks | `https://mailpilots.net/billing/webhook/stripe`, তারপর `STRIPE_WEBHOOK_SECRET` লাইভের `.env`-এ |

লোকালের ঠিকানাগুলো (`localhost`, `127.0.0.1`, LAN IP) মুছবে না। ওগুলো থাকলে লোকালও চলতে থাকবে।

## ৭. Deploy-এর পর যাচাই

- [ ] `https://mailpilots.net/healthz`: `"ok": true` আর `"last_error": null` (কয়েক মিনিট পরে দেখো)
- [ ] `https://mailpilots.net/api/v1/auth/social/providers`: `google` আর `github` দুটোই `"configured": true`
- [ ] `https://mailpilots.net/login`: Google আর GitHub বোতাম আছে, দুটো দিয়েই লগইন হয়
- [ ] Setup পেজ থেকে Gmail connect করলে mailpilots.net-এ ফিরে আসে
- [ ] Notification bell কাজ করে
- [ ] `http://mailpilots.net` খুললে `https://`-এ চলে যায়

## ৮. মোবাইল অ্যাপ

- `eas build --profile preview` বা `--profile production` দিলে অ্যাপ নিজেই `https://mailpilots.net` ব্যবহার করবে ([eas.json](../../mailPilotApp/eas.json)-এর `env`)।
- Expo Go আর `development` build আগের মতোই লোকাল PC-র সার্ভারে যাবে।
- Release build-এ native Google login চালাতে: `eas credentials` থেকে production keystore-এর SHA-1 নাও (Play Store-এ দিলে Play Console → App signing-এর SHA-1-ও)। Firebase → Project settings → Android app-এ যোগ করো, নতুন `google-services.json` ডাউনলোড করে অ্যাপ ফোল্ডারে বদলে দাও।

## ৯. লোকালে কাজ চালানো (কিছু বদলায়নি)

```powershell
python manage.py runserver 0.0.0.0:8000
```
লোকালের `.env`-এ `MAILPILOT_ENV=local` আছে। `SITE_URL` খালি রাখো, তাহলে লিংকগুলো যে ঠিকানায় খুলছ সেটাই মানবে।

## ১০. কিছু ভুল হলে

| সমস্যা | কারণ ও সমাধান |
|---|---|
| অ্যাপ চালু হয় না, `ImproperlyConfigured: MAILPILOT_ENV=production` | `.env`-এ `SITE_URL` বা শক্ত `DJANGO_SECRET_KEY` নেই |
| ব্রাউজারে "too many redirects" | proxy `X-Forwarded-Proto` পাঠাচ্ছে না। nginx ঠিক করো, বা `DJANGO_BEHIND_HTTPS_PROXY=true` দাও |
| `400 Bad Request` | অন্য কোনো domain দিয়ে খুলছ। সেটা `DJANGO_ALLOWED_HOSTS`-এ যোগ করো |
| লগইন বা ফর্মে `403 CSRF` | proxy `Host` / `X-Forwarded-Host` পাঠাচ্ছে না, অথবা `SITE_URL` ভুল |
| Google/GitHub: `unauthorized_domain` | Firebase Authorized domains-এ mailpilots.net নেই |
| Gmail connect: `redirect_uri_mismatch` | Google Cloud-এ `https://mailpilots.net/api/gmail/oauth/callback` নেই, অথবা `.env`-এর `OAUTH_REDIRECT_URI` আলাদা |
| পুরনো mailbox আর কাজ করে না | `FIELD_ENCRYPTION_KEY` বদলে গেছে। backup `.env` থেকে পুরনোটা ফিরিয়ে দাও |

**আগের অবস্থায় ফেরা (rollback):** পুরনো কোড ফিরিয়ে আনো (`git checkout <আগের commit>` বা পুরনো ফোল্ডার), backup রাখা `.env` বসাও, তারপর রিস্টার্ট করো। নতুন migration (`0053`) শুধু দুটো টেবিল আর একটা খালি-রাখা-যায় এমন কলাম যোগ করে, তাই পুরনো কোড একই database-এ চলবে। একদম আগের অবস্থা চাইলে ধাপ ১-এর dump থেকে `pg_restore` করো।
