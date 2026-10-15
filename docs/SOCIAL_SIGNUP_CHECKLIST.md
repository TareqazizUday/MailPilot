# অ্যাপে Signup / Social Login চালু করার চেকলিস্ট

Social login এখন শুধু **Google** আর **GitHub**, দুটোই Firebase Authentication দিয়ে। পুরো সেটআপ: `docs/SOCIAL_LOGIN_SETUP.md`। Email/password signup key ছাড়াই কাজ করে।

## ১. যা যা লাগবে

- [ ] **Firebase প্রজেক্ট** আর তার Web app config (`FIREBASE_*`)
- [ ] **Google:** Firebase → Sign-in method → Google → Enable
- [ ] **GitHub:** GitHub OAuth App (callback `https://<project-id>.firebaseapp.com/__/auth/handler`), তারপর Firebase → Sign-in method → GitHub → Client ID + Secret
- [ ] Firebase → Authorized domains-এ সাইটের host (`127.0.0.1`, LAN IP, আসল ডোমেইন)

## ২. সার্ভারের `.env`

```env
SITE_URL=https://your-domain
FIREBASE_PROJECT_ID=
FIREBASE_API_KEY=
FIREBASE_AUTH_DOMAIN=
FIREBASE_APP_ID=
# ঐচ্ছিক: Firebase ছাড়া Google redirect flow
GOOGLE_LOGIN_CLIENT_ID=
GOOGLE_LOGIN_CLIENT_SECRET=
```

তারপর runserver রিস্টার্ট করো। চেক করার জন্য `GET /api/v1/auth/social/providers` ডাকো; `google` আর `github` দুটোই `configured: true` দেখাবে।

## ৩. অ্যাপের `.env`

```env
EXPO_PUBLIC_API_BASE_URL=https://your-domain
EXPO_PUBLIC_FIREBASE_API_KEY=
EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN=
EXPO_PUBLIC_FIREBASE_PROJECT_ID=
EXPO_PUBLIC_FIREBASE_APP_ID=
EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID=
```

## ৪. অ্যাপের flow

- **Google (dev/production build):** native Google Sign-In → Firebase `signInWithCredential` → `POST /api/v1/auth/social/token { provider: "firebase", id_token }`।
- **Google (Expo Go) আর GitHub (সবসময়):** `WebBrowser.openAuthSessionAsync("{API_BASE}/auth/social/firebase/app?provider=<google|github>&return_to=<app link>")` → ফেরত লিংকে `status=ok&code=...` → ২ মিনিটের মধ্যে `POST /api/v1/auth/social/exchange { code }`।
- **অ্যাপের web build:** Firebase popup → `POST /api/v1/auth/social/token { provider: "firebase", id_token, access_token }` (GitHub-এর জন্য `access_token` বাধ্যতামূলক)।
- `status=error` এলে `error` কোড অনুযায়ী মেসেজ দেখাও (`docs/API_REFERENCE.md`-এর Auth অংশ)।
- Token সেভ করো, তারপর `registerForPush()` ডাকো।

## ৫. Email/password signup (key লাগে না)

```
POST /api/v1/auth/signup
{ "first_name", "last_name", "email", "password", "password2", "terms": true }
```

- সফল হলে `201` আসে, সাথে `access` আর `refresh` টোকেন। আলাদা লগইন লাগবে না।
- ভুল হলে `400` আসে, আর `error`-এর মেসেজটা সরাসরি ইউজারকে দেখাও।
- `first_name` আর `email` বাধ্যতামূলক। পাসওয়ার্ড কমপক্ষে ৮ অক্ষর, `password2` একই হতে হবে, আর `terms` অবশ্যই `true` হতে হবে।

## ৬. টেস্ট

- [ ] Email signup করে নতুন অ্যাকাউন্ট দিয়ে লগইন হচ্ছে কিনা দেখো
- [ ] অ্যাপে Google আর GitHub বোতাম দেখা যাচ্ছে কিনা দেখো
- [ ] নতুন অ্যাকাউন্ট দিয়ে লগইন করো, উত্তরে `created: true` আসা উচিত
- [ ] একই ইমেইলের আগের অ্যাকাউন্ট দিয়ে (Google বা GitHub) লগইন করো, `created: false` আসা উচিত
- [ ] বাতিল (cancel) করলে কোনো error ছাড়া লগইন স্ক্রিনে থাকে কিনা দেখো
