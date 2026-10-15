# Google আর GitHub দিয়ে অ্যাকাউন্ট খোলার সেটআপ

MailPilot-এ এই দুটো দিয়ে লগইন আর signup-এর কোড আগে থেকেই তৈরি আছে, ওয়েব আর মোবাইল অ্যাপ দুটোতেই। দুটোই **Firebase Authentication** দিয়ে চলে। Google-এর একটা পুরনো redirect flow-ও আছে, Firebase না থাকলে সেটা ব্যবহার হয়। GitHub শুধু Firebase দিয়েই চলে।

---

## ০. দুটোর জন্যই যা লাগবে

- [ ] একটা Firebase প্রজেক্ট (এখন: `mailpilot-f4add`)।
- [ ] ডোমেইনে লাইভ **Privacy Policy** আর **Terms of Service** পেজ (Google consent screen publish করতে লাগে)।
- [ ] সার্ভারের `.env`-এ Firebase Web app config (Project settings → General → Your apps → Web app):
  ```env
  FIREBASE_PROJECT_ID=তোমার-project-id
  FIREBASE_API_KEY=...
  FIREBASE_AUTH_DOMAIN=তোমার-project-id.firebaseapp.com
  FIREBASE_APP_ID=...
  ```
- [ ] Firebase → **Authentication → Settings → Authorized domains**-এ সাইটের প্রতিটা host যোগ করো। `localhost` আগে থেকেই থাকে; `127.0.0.1`, LAN IP (যেমন `10.57.254.37`) বা আসল ডোমেইন নিজে যোগ করতে হয়। না করলে `unauthorized_domain` error আসে।
- [ ] Firebase → **Authentication → Settings → User account linking → Create multiple accounts for each identity provider**। এতে একই email-এ Google আর GitHub দুটোই চলবে, আর MailPilot email মিলিয়ে একই অ্যাকাউন্টে ঢোকাবে।

`.env` বদলালে সার্ভার রিস্টার্ট করতে হবে।

---

## ১. Google

**খরচ:** ফ্রি। **সময়:** ৩০ মিনিট, আর লোগো দেখাতে চাইলে verification-এ ২-৫ দিন।

### Firebase দিয়ে (ওয়েব + অ্যাপ)
1. Firebase → **Authentication → Sign-in method → Google → Enable** → Save।
2. **Project settings → Your apps → Android** → package name + SHA-1 (`eas credentials`) → `google-services.json` ডাউনলোড। **iOS** → bundle ID → `GoogleService-Info.plist` ডাউনলোড।
3. ওয়েবের Google বোতাম Firebase popup খোলে। অ্যাপে dev/production build-এ native Google Sign-In, আর Expo Go-তে in-app browser দিয়ে চলে।
4. Google Cloud → **OAuth consent screen** → **Publish app** চাপো, না হলে শুধু Test users লগইন করতে পারবে।

### পুরনো redirect flow (Firebase ছাড়া, ঐচ্ছিক)
1. [console.cloud.google.com](https://console.cloud.google.com) → **Credentials → Create credentials → OAuth client ID** → Type: **Web application**।
2. Authorized redirect URI: `https://your-domain/auth/social/google/callback` (লোকালে `http://localhost:8000/auth/social/google/callback`)। শেষে `/` দেবে না।
3. `.env`:
   ```env
   GOOGLE_LOGIN_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
   GOOGLE_LOGIN_CLIENT_SECRET=xxxxxxxx
   ```

### Native Google Sign-In (Firebase ছাড়া, ঐচ্ছিক)
Android/iOS OAuth client ID-গুলো কমা দিয়ে `.env`-এ দাও, তাহলে অ্যাপ `POST /api/v1/auth/social/token { provider: "google", id_token }` ডাকতে পারবে:
```env
GOOGLE_LOGIN_MOBILE_CLIENT_IDS=android-id.apps.googleusercontent.com,ios-id.apps.googleusercontent.com
```

---

## ২. GitHub

**খরচ:** ফ্রি। **সময়:** ১০ মিনিট। কোনো review বা verification লাগে না।

### ধাপ
1. Firebase → **Authentication → Sign-in method → Add new provider → GitHub** → Enable। নিচে একটা **callback URL** দেখাবে: `https://mailpilot-f4add.firebaseapp.com/__/auth/handler` — কপি করো। (Client ID/Secret এখনো খালি রাখো।)
2. GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App** ([github.com/settings/developers](https://github.com/settings/developers)):
   - Application name: `MailPilot`
   - Homepage URL: সাইটের ঠিকানা (যেমন `https://your-domain`, লোকালে `http://localhost:8000`)
   - Authorization callback URL: ধাপ ১-এর URL হুবহু
   - Register application চাপো।
3. **Client ID** কপি করো, তারপর **Generate a new client secret** চেপে secret কপি করো (একবারই দেখায়)।
4. Firebase-এর GitHub provider-এ Client ID আর Client Secret বসাও → **Save**।

সার্ভারের `.env`-এ GitHub-এর জন্য আলাদা কিছু লাগে না। Firebase-এর চারটা মান থাকলেই GitHub বোতাম চালু হয়।

### GitHub email কীভাবে যাচাই হয়
Firebase GitHub-এর email-কে কখনো "verified" বলে না। তাই সার্ভার popup থেকে পাওয়া GitHub access token দিয়ে GitHub API থেকে নিজে যাচাই করে:
- `GET https://api.github.com/user` — GitHub user id Firebase token-এর GitHub id-র সাথে মিলতে হবে, না মিললে `invalid_token`।
- `GET https://api.github.com/user/emails` — একটা **verified** email লাগবে (primary থাকলে সেটা)। না থাকলে `email_unverified` বা `email_missing`।

এজন্য popup `user:email` scope চায়, আর ওয়েব/অ্যাপ Firebase ID token-এর সাথে `access_token`-ও পাঠায়। access token না পাঠালে `access_token_required`।

### অ্যাপে
GitHub-এর native SDK নেই। অ্যাপ সবসময় in-app browser-এ `/auth/social/firebase/app?provider=github&return_to=...` খোলে, সেখানে Firebase popup চলে, তারপর one-time code দিয়ে অ্যাপে ফেরে (`POST /api/v1/auth/social/exchange`)।

---

## ৩. সব সেট করার পর

1. সার্ভার রিস্টার্ট করো।
2. চেক করো: `https://your-domain/api/v1/auth/social/providers` খুললে `google` আর `github` দুটোই `"configured": true` দেখাবে।
3. ওয়েবের Login/Signup পেজ আর অ্যাপের লগইন স্ক্রিনে দুটো বোতাম দেখা যাবে।
4. অ্যাপের `.env`-এ `EXPO_PUBLIC_API_BASE_URL` সার্ভারের ঠিকানা হতে হবে, আর সেই host Firebase Authorized domains-এ থাকতে হবে।

---

## ৪. অ্যাকাউন্ট কীভাবে তৈরি হয় (দুটোর জন্যই একই নিয়ম)

- **Verified ইমেইল, আর আগে কোনো অ্যাকাউন্ট নেই:** নতুন অ্যাকাউন্ট তৈরি হয় Starter plan-এ, পাসওয়ার্ড ছাড়া। পরে "Forgot password" দিয়ে পাসওয়ার্ড সেট করা যায়।
- **একই ইমেইলে আগে থেকে অ্যাকাউন্ট আছে:** নতুন না বানিয়ে আগের অ্যাকাউন্টেই লগইন হয়। তাই Google দিয়ে খুলে পরে GitHub দিয়ে ঢুকলেও একই অ্যাকাউন্ট পাবে, যদি GitHub-এ সেই email verified থাকে।
- **ইমেইল নেই বা verified নয়:** লগইন হয় না, error মেসেজ দেখায়।
- **অ্যাকাউন্ট বন্ধ (inactive) থাকলে:** লগইন হয় না।

---

## ৫. টেস্ট চেকলিস্ট

দুটো provider-এর জন্য:
- [ ] ওয়েবের Signup পেজ থেকে নতুন অ্যাকাউন্ট খোলো, Dashboard-এ পৌঁছায় কিনা দেখো।
- [ ] লগআউট করে Login পেজ থেকে আবার ঢোকো, একই অ্যাকাউন্ট খোলে কিনা দেখো।
- [ ] মোবাইল অ্যাপ থেকে লগইন করো। নতুন অ্যাকাউন্ট হলে `created: true`, আগের অ্যাকাউন্ট হলে `false` আসবে।
- [ ] popup বন্ধ করে দাও, কোনো error ছাড়াই আগের পেজে থাকে কিনা দেখো।
- [ ] Google আর GitHub-এ একই email থাকলে দুটো দিয়েই একই অ্যাকাউন্টে ঢোকে কিনা দেখো।

## ৬. সাধারণ সমস্যা

| সমস্যা | কারণ ও সমাধান |
|---|---|
| "not available yet" | `.env`-এ Firebase মান নেই, অথবা সার্ভার রিস্টার্ট হয়নি |
| `unauthorized_domain` | সাইটের host Firebase Authorized domains-এ নেই |
| GitHub: "redirect_uri is not associated with this application" | GitHub OAuth App-এর callback URL Firebase-এর `__/auth/handler` URL-এর সাথে হুবহু মিলছে না |
| GitHub: `not_configured` / operation-not-allowed | Firebase-এ GitHub provider Enable বা Save করা হয়নি |
| GitHub: `email_unverified` | GitHub-এ email verify করা নেই (GitHub → Settings → Emails) |
| `account_exists` | Firebase-এ account linking "one account per email"-এ আছে; "multiple accounts" করো |
| Google: `redirect_uri_mismatch` | (redirect flow) console-এর redirect URI আর আসল ডোমেইন হুবহু মিলছে না |
| Google: `access_denied` বা "app not verified" | consent screen এখনো "Testing" অবস্থায়, Publish করো |
| অ্যাপে `invalid_return_to` | অ্যাপের `return_to` লিংক `mailpilot://`, `exp://` বা অনুমোদিত URL নয় |
| অ্যাপে `invalid_or_expired_code` | ২ মিনিটের বেশি দেরি হয়েছে, অথবা code দুবার ব্যবহার করা হয়েছে |
