# MailPilot সবার জন্য চালু করার গাইড (Google লগইন + Gmail সংযোগ)

এই গাইডে দুটো আলাদা জিনিস আছে, গুলিয়ে ফেলো না:

| | কী করে | Google-এর অনুমতি | কতটা কঠিন |
|---|---|---|---|
| **অংশ ক: Google দিয়ে লগইন/signup** | ইউজার "Continue with Google" চেপে অ্যাকাউন্ট খোলে | `openid email profile` (সাধারণ scope) | সহজ, ১-৩ দিন |
| **অংশ খ: Gmail inbox সংযোগ** | MailPilot ইউজারের মেইল পড়ে আর রিপ্লাই পাঠায় | `gmail.readonly`, `gmail.modify`, `gmail.send`, `gmail.compose` (restricted scope) | কঠিন, কয়েক সপ্তাহ থেকে মাস, খরচ আছে |

অংশ ক আগে করো। অংশ খ শেষ না হলেও ইউজাররা অ্যাকাউন্ট খুলতে পারবে, আর SMTP/IMAP দিয়ে মেইল সংযোগ করতে পারবে (অংশ গ দেখো)।

---

## শুরুর আগে যা লাগবে

- [ ] **নিজের ডোমেইন** (যেমন `mailpilot.app`)। ngrok দিয়ে টেস্ট চলে, কিন্তু Google publish বা verify করতে আসল ডোমেইন লাগবে।
- [ ] **HTTPS-সহ প্রোডাকশন সার্ভার** (IIS বা waitress-এর সামনে SSL)।
- [ ] ডোমেইনে তিনটা পাবলিক পেজ: হোমপেজ, **Privacy Policy**, **Terms of Service**। MailPilot-এ এগুলো আগে থেকেই আছে, শুধু ডোমেইনে লাইভ থাকতে হবে।
- [ ] একটা **Google অ্যাকাউন্ট**, যেটা কোম্পানির নামে থাকবে আর যেটা দিয়ে Google Cloud প্রজেক্ট চালাবে।
- [ ] একটা **সাপোর্ট ইমেইল** (যেমন `support@your-domain`)।

---

## অংশ ক: Google দিয়ে লগইন সবার জন্য খোলা

### ক১. Google Cloud প্রজেক্ট

1. [console.cloud.google.com](https://console.cloud.google.com)-এ গিয়ে নতুন প্রজেক্ট বানাও, যেমন "MailPilot Production"।
2. **APIs & Services → OAuth consent screen** (নতুন UI-তে **Google Auth Platform → Branding**):
   - User type: **External**
   - App name: `MailPilot`
   - User support email: তোমার সাপোর্ট ইমেইল
   - App logo: ১২০x১২০ PNG (ঐচ্ছিক, তবে দিলে brand verification লাগবে)
   - App domain: হোমপেজ, Privacy Policy আর Terms-এর লিংক
   - Authorized domains: `your-domain`
   - Developer contact: তোমার ইমেইল
3. **Scopes** (নতুন UI-তে **Data Access**) অংশে শুধু এই তিনটা রাখো: `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`।

### ক২. OAuth Client ID

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**।
2. Application type: **Web application**।
3. Authorized redirect URIs:
   ```
   https://your-domain/auth/social/google/callback
   ```
   লোকাল টেস্টের জন্য চাইলে এটাও যোগ করো: `http://localhost:8000/auth/social/google/callback`
4. Client ID আর Client Secret কপি করে রাখো।

### ক৩. সার্ভারের `.env`

```env
SITE_URL=https://your-domain
GOOGLE_LOGIN_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
GOOGLE_LOGIN_CLIENT_SECRET=xxxxxxxx
DJANGO_ALLOWED_HOSTS=your-domain
DJANGO_SECURE_SSL_REDIRECT=true
```

সার্ভার রিস্টার্ট করো। তারপর `https://your-domain/api/v1/auth/social/providers` খুললে Google-এর পাশে `"configured": true` দেখাবে।

### ক৪. সবার জন্য Publish

1. **OAuth consent screen → Publishing status → Publish app**। স্ট্যাটাস "Testing" থেকে বদলে "In production" হবে।
2. Publish না করলে শুধু "Test users" তালিকার ইমেইলগুলো (সর্বোচ্চ ১০০টা) লগইন করতে পারবে, বাকিরা `access_denied` পাবে।
3. যেহেতু শুধু সাধারণ scope চাওয়া হচ্ছে, তাই বড় কোনো রিভিউ লাগবে না।
4. **Brand verification:** লোগো বা অ্যাপের নাম দেখাতে চাইলে Google ডোমেইনের মালিকানা যাচাই করবে।
   - [Google Search Console](https://search.google.com/search-console)-এ ডোমেইন verify করো। ডোমেইনের DNS-এ একটা TXT রেকর্ড যোগ করতে হয়।
   - Consent screen-এ "Submit for verification" চাপো। সাধারণত ২-৫ কর্মদিবস লাগে।
   - এটা না করলেও লগইন চলবে। শুধু consent screen-এ তোমার লোগোর বদলে ডোমেইনের নাম দেখাবে।

### ক৫. ঐচ্ছিক: Facebook আর LinkedIn

| Provider | কোথায় | Redirect URI | `.env` |
|---|---|---|---|
| Facebook | developers.facebook.com → Create App → Facebook Login | `https://your-domain/auth/social/facebook/callback` | `FACEBOOK_LOGIN_CLIENT_ID`, `FACEBOOK_LOGIN_CLIENT_SECRET` |
| LinkedIn | linkedin.com/developers → Create app → "Sign In with LinkedIn using OpenID Connect" | `https://your-domain/auth/social/linkedin/callback` | `LINKEDIN_LOGIN_CLIENT_ID`, `LINKEDIN_LOGIN_CLIENT_SECRET` |

Facebook অ্যাপকে "Live" মোডে নিতে হবে, আর তার জন্য Privacy Policy URL আর Data Deletion URL লাগবে। LinkedIn-এ কোম্পানির LinkedIn পেজ লাগবে।

### ক৬. মোবাইল অ্যাপ

```env
EXPO_PUBLIC_API_BASE_URL=https://your-domain
EXPO_PUBLIC_WEB_BASE_URL=https://your-domain
```

অ্যাপের `app.json`-এ `"scheme": "mailpilot"` থাকতে হবে। লগইন flow `docs/SOCIAL_SIGNUP_CHECKLIST.md`-এ আছে।

### ক৭. টেস্ট

- [ ] এমন একটা Gmail দিয়ে লগইন করো, যেটা Test users তালিকায় নেই। এটা কাজ করলে publish ঠিক হয়েছে।
- [ ] ওয়েব আর অ্যাপ দুই জায়গা থেকেই লগইন করো।
- [ ] নতুন ইমেইলে লগইন করলে নতুন অ্যাকাউন্ট (Starter plan) তৈরি হয় কিনা দেখো। আগের ইমেইলে লগইন করলে আগের অ্যাকাউন্টই খোলে কিনা দেখো।

---

## অংশ খ: Gmail inbox সংযোগ সবার জন্য

### খ১. এখনকার অবস্থা

প্রতিটা ইউজারকে নিজের Google Cloud প্রজেক্ট বানিয়ে `client_secret.json` আপলোড করতে হয় (Setup পেজে)। এতে Google-এর কোনো ভেরিফিকেশন লাগে না, কিন্তু সাধারণ ইউজারের জন্য এটা খুব কঠিন, আর বেশিরভাগ ইউজার এখানেই আটকে যাবে।

"সবার জন্য এক ক্লিকে Connect Gmail" চাইলে MailPilot-এর **নিজের একটা কেন্দ্রীয় OAuth client** লাগবে। এর জন্য Google-এর **restricted scope verification** পার হতে হবে।

### খ২. কেন এটা কঠিন

এখন MailPilot এই scope-গুলো চায়: `gmail.readonly`, `gmail.modify`, `gmail.send`, `gmail.compose`। এর মধ্যে `gmail.readonly` আর `gmail.modify` হলো **restricted** scope। Google এগুলো অনুমোদন করে শুধু তখন:
1. অ্যাপটা Google-এর রিভিউ পাস করলে, আর
2. একটা স্বীকৃত সংস্থা দিয়ে **CASA security assessment** করানো হলে, এবং প্রতি বছর আবার করালে।

ভেরিফিকেশন ছাড়া "In production" অ্যাপ সর্বোচ্চ **১০০ জন** ইউজার পর্যন্ত চালানো যায়। তাদের প্রত্যেকে "Google hasn't verified this app" সতর্কবার্তা দেখবে।

### খ৩. ধাপগুলো

**ধাপ ১: scope কমানো।** এটা কোডে পরিবর্তন।
- `email_automation/settings.py`-এ এখন চারটা scope আছে। `gmail.modify` নিজেই পড়া, লেখা আর পাঠানো সব করতে পারে। তাই শুধু `gmail.modify` রাখলে রিভিউ সহজ হয়।
- বদলানোর পর আগের সংযুক্ত অ্যাকাউন্টগুলোকে একবার আবার সংযোগ করতে হতে পারে।

**ধাপ ২: কেন্দ্রীয় OAuth client।** এটাও কোডে পরিবর্তন।
- অংশ ক-এর একই Google প্রজেক্টে **Gmail API** চালু করো (APIs & Services → Library → Gmail API → Enable)।
- নতুন একটা Web OAuth client বানাও, redirect URI দাও `https://your-domain/api/gmail/oauth/callback`।
- সার্ভারে এই client-কে ডিফল্ট হিসেবে ব্যবহার করতে হবে, যাতে ইউজারকে আর `client_secret.json` আপলোড করতে না হয়। এটা এখনকার কোডে নেই, আলাদা করে বানাতে হবে।
- `.env`-এ `OAUTH_REDIRECT_URI=https://your-domain/api/gmail/oauth/callback` দিতে হবে।

**ধাপ ৩: Privacy Policy আপডেট।** Google এই বিষয়গুলো স্পষ্ট লেখা চায়:
- MailPilot কোন Gmail ডাটা পড়ে, কেন পড়ে, কোথায় রাখে, কতদিন রাখে, আর কীভাবে মুছে ফেলা যায়।
- AI বা LLM-এ মেইলের বিষয়বস্তু পাঠানো হয় কিনা, আর সেই ডাটা মডেল ট্রেনিংয়ে ব্যবহার হয় না, এটা স্পষ্ট করে লিখতে হবে।
- **Limited Use** ঘোষণা। এই বাক্যটা প্রায় হুবহু রাখতে হয়:
  > MailPilot's use and transfer of information received from Google APIs to any other app will adhere to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

**ধাপ ৪: Demo video।**
- YouTube-এ একটা "Unlisted" ভিডিও দিতে হবে, যেখানে দেখা যাবে লগইন, তারপর "Connect Gmail", তারপর Google consent screen (ব্রাউজারের URL bar-এ client ID দেখা যেতে হবে)।
- এরপর দেখাতে হবে প্রতিটা scope কোথায় ব্যবহার হচ্ছে: মেইল পড়া, draft বানানো, রিপ্লাই পাঠানো।
- ভিডিও ইংরেজিতে হতে হবে।

**ধাপ ৫: Verification সাবমিট।**
- Consent screen-এ Gmail scope যোগ করো, তারপর "Prepare for verification" চাপো।
- প্রতিটা scope কেন দরকার তার ব্যাখ্যা লেখো, আর ভিডিওর লিংক দাও।
- Google ইমেইলে প্রশ্ন করতে পারে, উত্তর দিতে হবে। সাধারণত কয়েক সপ্তাহ লাগে।

**ধাপ ৬: CASA security assessment।**
- Google ইমেইলে assessment-এর tier জানাবে। সাধারণত Tier 2 হয়।
- Google-এর তালিকাভুক্ত কোনো ল্যাব বেছে নাও (App Defense Alliance-এর সাইটে তালিকা আছে)।
- ল্যাব তোমার অ্যাপ স্ক্যান করবে আর একটা প্রশ্নমালা দেবে। যা সমস্যা ধরা পড়বে, সেগুলো ঠিক করতে হবে।
- **খরচ:** ল্যাব আর tier অনুযায়ী আনুমানিক কয়েকশো থেকে কয়েক হাজার ডলার। সাইন করার আগে ল্যাবের সাথে দাম নিশ্চিত করো।
- **প্রতি বছর** আবার assessment করাতে হয়।

**ধাপ ৭: অনুমোদন।** এরপর যেকোনো ইউজার কোনো সতর্কবার্তা ছাড়াই এক ক্লিকে Gmail সংযোগ করতে পারবে।

### খ৪. CASA-র আগে যা প্রস্তুত রাখা ভালো

- [ ] প্রোডাকশনে `DJANGO_DEBUG=false`, HTTPS, HSTS, আর secure cookie চালু থাকতে হবে।
- [ ] OAuth token ডাটাবেসে encrypted থাকতে হবে। MailPilot এটা আগে থেকেই করে (`*_enc` ফিল্ড)।
- [ ] ইউজার নিজের অ্যাকাউন্ট আর ডাটা মুছতে পারবে, আর Gmail disconnect করলে token মুছে যাবে।
- [ ] সার্ভার আর ডাটাবেসের অ্যাক্সেস সীমিত, ব্যাকআপও encrypted।
- [ ] dependency আপডেট করা আর জানা দুর্বলতা নেই (`pip-audit` চালিয়ে দেখো)।
- [ ] লগে মেইলের বিষয়বস্তু বা token লেখা হয় না।

---

## অংশ গ: ভেরিফিকেশনের অপেক্ষায় থাকাকালীন বিকল্প

অংশ খ শেষ হতে সময় লাগবে। এই সময়ে:

1. **SMTP/IMAP দিয়ে সংযোগ (সবচেয়ে সহজ):**
   - ইউজার নিজের Gmail-এ 2-Step Verification চালু করে একটা **App Password** বানাবে, তারপর MailPilot-এর Setup-এ SMTP/IMAP অপশনে সেটা দেবে।
   - এতে Google-এর কোনো ভেরিফিকেশন লাগে না, আর MailPilot এটা আগে থেকেই সাপোর্ট করে।
   - Setup পেজে ধাপে ধাপে নির্দেশনা আর স্ক্রিনশট দিলে ইউজারের সুবিধা হবে।
2. **১০০ জন পর্যন্ত beta:** কেন্দ্রীয় client "In production" রেখে ভেরিফিকেশন ছাড়াই চালানো যায়। ইউজাররা "unverified app" সতর্কবার্তা দেখবে, "Advanced → Go to MailPilot" চেপে এগোতে হবে।
3. **Google Workspace কোম্পানি:** কোনো প্রতিষ্ঠানের admin তার Workspace-এ MailPilot-কে "trusted" করে দিলে, সেই প্রতিষ্ঠানের ইউজারদের জন্য ভেরিফিকেশন লাগে না।

---

## সার্বিক ক্রম (সুপারিশ)

1. **সপ্তাহ ১:** ডোমেইন, HTTPS আর প্রোডাকশন সার্ভার। অংশ ক শেষ করো, তাহলে সবাই Google দিয়ে অ্যাকাউন্ট খুলতে পারবে।
2. **সপ্তাহ ১-২:** Setup পেজে Gmail App Password দিয়ে SMTP/IMAP সংযোগের সহজ নির্দেশনা দাও (অংশ গ-এর ১ নম্বর)।
3. **সপ্তাহ ২-৩:** কোডে scope কমানো আর কেন্দ্রীয় OAuth client চালু করা (অংশ খ, ধাপ ১-২)। Privacy Policy আর ভিডিও তৈরি।
4. **সপ্তাহ ৩ থেকে কয়েক মাস:** Google verification আর CASA।
5. অনুমোদনের পর Setup-এ এক ক্লিকে "Connect Gmail" সবার জন্য চালু করো।

## দ্রুত চেকলিস্ট

- [ ] ডোমেইন + HTTPS + প্রোডাকশন সার্ভার
- [ ] Privacy Policy আর Terms ডোমেইনে লাইভ
- [ ] Google Cloud প্রজেক্ট, consent screen, Login OAuth client
- [ ] `.env`: `SITE_URL`, `GOOGLE_LOGIN_CLIENT_ID`, `GOOGLE_LOGIN_CLIENT_SECRET`
- [ ] Consent screen **Publish**
- [ ] Search Console-এ ডোমেইন verify (লোগো দেখাতে চাইলে)
- [ ] অ্যাপের `EXPO_PUBLIC_API_BASE_URL` প্রোডাকশন ডোমেইনে
- [ ] SMTP/IMAP App Password নির্দেশনা Setup পেজে
- [ ] কোড: Gmail scope কমানো + কেন্দ্রীয় OAuth client
- [ ] Gmail API চালু, Gmail OAuth client, `OAUTH_REDIRECT_URI`
- [ ] Privacy Policy-তে Google ডাটা ব্যবহার আর Limited Use ঘোষণা
- [ ] Demo video (YouTube, Unlisted)
- [ ] Verification সাবমিট
- [ ] CASA assessment (প্রতি বছর)
