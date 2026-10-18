from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings

_KEYS = {
    "GOOGLE_LOGIN_CLIENT_ID": "gid",
    "GOOGLE_LOGIN_CLIENT_SECRET": "gsecret",
    "GOOGLE_LOGIN_MOBILE_CLIENT_IDS": "android-id, ios-id",
}
_NO_KEYS = {k: "" for k in _KEYS}
_FIREBASE = {"FIREBASE_PROJECT_ID": "mp-proj", "FIREBASE_API_KEY": "web-key"}
_NO_FIREBASE = {k: "" for k in _FIREBASE}
_RETURN_TO = "mailpilot://auth/social"
_BASE = "/api/v1/auth/social"


def _resp(status: int, data: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data
    return r


def _provider_http(profile: dict):
    """Patch token exchange + profile fetch done by ``core.social_auth``."""
    return (
        patch("core.social_auth.requests.post", return_value=_resp(200, {"access_token": "t"})),
        patch(
            "core.social_auth.requests.get",
            side_effect=lambda url, **kw: _resp(200, {"access_token": "t"}) if "access_token" in url else _resp(200, profile),
        ),
    )


@override_settings(SECURE_SSL_REDIRECT=False)
@patch.dict(os.environ, _KEYS)
class MobileSocialLoginTests(TestCase):
    def setUp(self):
        cache.clear()

    def _authorize(self, provider="google", return_to=_RETURN_TO):
        return self.client.get(f"{_BASE}/{provider}/authorize-url", {"return_to": return_to})

    def _deep_link(self, provider: str, profile: dict, **callback_params) -> dict:
        state = self._authorize(provider).json()["state"]
        post, get = _provider_http(profile)
        with post, get:
            resp = self.client.get(
                f"/auth/social/{provider}/callback", {"state": state, "code": "abc", **callback_params}
            )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(_RETURN_TO + "?"))
        return {k: v[0] for k, v in parse_qs(urlparse(resp["Location"]).query).items()}

    def _providers(self) -> dict[str, bool]:
        data = self.client.get(f"{_BASE}/providers").json()
        return {p["id"]: p["configured"] for p in data["providers"]}

    def test_providers_list(self):
        with patch.dict(os.environ, _FIREBASE):
            self.assertEqual(self._providers(), {"google": True, "github": True})
        with patch.dict(os.environ, _NO_FIREBASE):
            self.assertEqual(self._providers(), {"google": True, "github": False})
        with patch.dict(os.environ, {**_NO_KEYS, **_NO_FIREBASE}):
            self.assertEqual(self._providers(), {"google": False, "github": False})

    def test_github_authorize_opens_github(self):
        with patch.dict(os.environ, {"GITHUB_LOGIN_CLIENT_ID": "gh-client", "GITHUB_LOGIN_CLIENT_SECRET": "gh-secret"}):
            data = self._authorize("github").json()
        url = urlparse(data["authorization_url"])
        q = parse_qs(url.query)
        self.assertEqual((url.netloc, url.path), ("github.com", "/login/oauth/authorize"))
        self.assertEqual(q["client_id"], ["gh-client"])
        self.assertIn("user:email", q["scope"][0])
        self.assertTrue(q["redirect_uri"][0].endswith("/auth/social/github/callback"))

    def test_github_callback_logs_in_with_verified_email(self):
        with patch.dict(os.environ, {"GITHUB_LOGIN_CLIENT_ID": "gh-client", "GITHUB_LOGIN_CLIENT_SECRET": "gh-secret"}):
            state = self._authorize("github").json()["state"]

        def get(url, **_kw):
            if str(url).endswith("/user/emails"):
                return _resp(200, [{"email": "octo@example.com", "verified": True, "primary": True}])
            if str(url).endswith("/user"):
                return _resp(200, {"id": 9, "name": "Octo Cat"})
            return _resp(404, {})

        with patch("core.social_auth.requests.post", return_value=_resp(200, {"access_token": "gho"})), patch(
            "core.social_auth.requests.get", side_effect=get
        ):
            resp = self.client.get("/auth/social/github/callback", {"state": state, "code": "abc"})
        self.assertEqual(resp.status_code, 302)
        query = {k: v[0] for k, v in parse_qs(urlparse(resp["Location"]).query).items()}
        self.assertEqual((query["status"], query["provider"]), ("ok", "github"))
        exchanged = self.client.post(f"{_BASE}/exchange", {"code": query["code"]}, content_type="application/json")
        self.assertEqual(exchanged.status_code, 200)
        self.assertEqual(exchanged.json()["user"]["email"], "octo@example.com")
        self.assertEqual(exchanged.json()["user"]["first_name"], "Octo")

    def test_github_callback_rejects_unverified_email(self):
        with patch.dict(os.environ, {"GITHUB_LOGIN_CLIENT_ID": "gh-client", "GITHUB_LOGIN_CLIENT_SECRET": "gh-secret"}):
            state = self._authorize("github").json()["state"]

        def get(url, **_kw):
            if str(url).endswith("/user/emails"):
                return _resp(200, [{"email": "octo@example.com", "verified": False, "primary": True}])
            if str(url).endswith("/user"):
                return _resp(200, {"id": 9, "name": "Octo Cat"})
            return _resp(404, {})

        with patch("core.social_auth.requests.post", return_value=_resp(200, {"access_token": "gho"})), patch(
            "core.social_auth.requests.get", side_effect=get
        ):
            resp = self.client.get("/auth/social/github/callback", {"state": state, "code": "abc"})
        query = {k: v[0] for k, v in parse_qs(urlparse(resp["Location"]).query).items()}
        self.assertEqual(query["error"], "email_unverified")
        self.assertFalse(User.objects.filter(email="octo@example.com").exists())

    def test_authorize_url(self):
        data = self._authorize("google").json()
        url = urlparse(data["authorization_url"])
        q = parse_qs(url.query)
        self.assertEqual(url.netloc, "accounts.google.com")
        self.assertEqual(q["client_id"], ["gid"])
        self.assertEqual(q["state"], [data["state"]])
        self.assertTrue(q["redirect_uri"][0].endswith("/auth/social/google/callback"))

    def test_authorize_url_errors(self):
        resp = self._authorize(return_to="https://evil.example.com/x")
        self.assertEqual((resp.status_code, resp.json()["error"]), (400, "invalid_return_to"))
        for provider in ("twitter", "facebook", "linkedin"):
            resp = self._authorize(provider=provider)
            self.assertEqual((resp.status_code, resp.json()["error"]), (404, "unknown_provider"))
        with patch.dict(os.environ, {"GITHUB_LOGIN_CLIENT_ID": "", "GITHUB_LOGIN_CLIENT_SECRET": "", **_NO_FIREBASE}):
            resp = self._authorize("github")
        self.assertEqual((resp.status_code, resp.json()["error"]), (503, "not_configured"))
        with patch.dict(os.environ, {"GITHUB_LOGIN_CLIENT_ID": "", "GITHUB_LOGIN_CLIENT_SECRET": "", **_FIREBASE}):
            resp = self._authorize("github")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("/auth/social/firebase/app", resp.json()["authorization_url"])
        self.assertIn("provider=github", resp.json()["authorization_url"])
        self.assertIn("autostart=1", resp.json()["authorization_url"])
        with patch.dict(os.environ, _NO_KEYS):
            resp = self._authorize()
        self.assertEqual((resp.status_code, resp.json()["error"]), (503, "not_configured"))

    def test_full_flow_returns_working_jwt(self):
        link = self._deep_link(
            "google", {"email": "App.User@Example.com", "email_verified": True, "given_name": "App"}
        )
        self.assertEqual((link["status"], link["provider"]), ("ok", "google"))
        resp = self.client.post(f"{_BASE}/exchange", {"code": link["code"]}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["created"])
        self.assertEqual(data["user"]["email"], "app.user@example.com")
        me = self.client.get("/api/v1/me", HTTP_AUTHORIZATION=f"Bearer {data['access']}")
        self.assertEqual(me.json()["user"]["email"], "app.user@example.com")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_code_is_single_use(self):
        link = self._deep_link("google", {"email": "x@example.com", "email_verified": True})
        first = self.client.post(f"{_BASE}/exchange", {"code": link["code"]}, content_type="application/json")
        second = self.client.post(f"{_BASE}/exchange", {"code": link["code"]}, content_type="application/json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual((second.status_code, second.json()["error"]), (400, "invalid_or_expired_code"))

    def test_expired_code_rejected(self):
        link = self._deep_link("google", {"email": "x@example.com", "email_verified": True})
        cache.delete(f"mailpilot:social_login_code:{link['code']}")
        resp = self.client.post(f"{_BASE}/exchange", {"code": link["code"]}, content_type="application/json")
        self.assertEqual(resp.json()["error"], "invalid_or_expired_code")

    def test_same_email_same_account_as_web(self):
        owner = User.objects.create_user("owner", "owner@example.com", "pw-12345678")
        link = self._deep_link("google", {"email": "OWNER@example.com", "email_verified": True})
        data = self.client.post(f"{_BASE}/exchange", {"code": link["code"]}, content_type="application/json").json()
        self.assertEqual((data["user"]["id"], data["created"]), (owner.id, False))

    def test_callback_errors_deep_link(self):
        link = self._deep_link("google", {"email": "x@example.com", "email_verified": False})
        self.assertEqual((link["status"], link["error"]), ("error", "email_unverified"))
        link = self._deep_link("google", {}, error="access_denied")
        self.assertEqual((link["status"], link["error"]), ("error", "cancelled"))

    def test_web_flow_unaffected(self):
        resp = self.client.get("/auth/social/google/callback", {"state": "unknown", "code": "abc"})
        self.assertIn("/login?social_error=state_mismatch", resp["Location"])


@override_settings(SECURE_SSL_REDIRECT=False)
@patch.dict(os.environ, _KEYS)
class NativeSocialTokenTests(TestCase):
    def setUp(self):
        cache.clear()

    def _post(self, payload: dict):
        return self.client.post(f"{_BASE}/token", payload, content_type="application/json")

    def _google(self, claims: dict):
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
            return self._post({"provider": "google", "id_token": "tok"})

    def test_google_valid_token(self):
        resp = self._google({"aud": "android-id", "email": "g@gmail.com", "email_verified": True, "given_name": "G"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["created"] and data["access"] and data["refresh"])
        self.assertEqual(data["user"]["first_name"], "G")

    def test_google_wrong_audience(self):
        resp = self._google({"aud": "someone-else", "email": "g@gmail.com", "email_verified": True})
        self.assertEqual((resp.status_code, resp.json()["error"]), (401, "invalid_token"))

    def test_google_bad_signature(self):
        with patch("google.oauth2.id_token.verify_oauth2_token", side_effect=ValueError("bad")):
            resp = self._post({"provider": "google", "id_token": "tok"})
        self.assertEqual(resp.json()["error"], "invalid_token")

    def test_google_unverified_email(self):
        resp = self._google({"aud": "gid", "email": "g@gmail.com", "email_verified": False})
        self.assertEqual((resp.status_code, resp.json()["error"]), (400, "email_unverified"))

    def test_google_requires_id_token(self):
        self.assertEqual(self._post({"provider": "google"}).json()["error"], "id_token_required")

    def test_google_missing_email_filled_from_same_account(self):
        claims = {"aud": "android-id", "sub": "google-sub", "email": ""}
        info = {"sub": "google-sub", "email": "second@gmail.com", "email_verified": True, "given_name": "Second"}
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims), patch(
            "core.social_auth.requests.get", return_value=_resp(200, info)
        ):
            resp = self._post({"provider": "google", "id_token": "tok", "access_token": "ya29"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user"]["email"], "second@gmail.com")

    def test_google_missing_email_rejects_other_account(self):
        claims = {"aud": "android-id", "sub": "google-sub", "email": ""}
        info = {"sub": "someone-else", "email": "victim@gmail.com", "email_verified": True}
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims), patch(
            "core.social_auth.requests.get", return_value=_resp(200, info)
        ):
            resp = self._post({"provider": "google", "id_token": "tok", "access_token": "ya29"})
        self.assertEqual((resp.status_code, resp.json()["error"]), (401, "invalid_token"))
        self.assertFalse(User.objects.filter(email="victim@gmail.com").exists())

    def _firebase(self, claims: dict | None = None, *, access_token: str = "", **kw):
        payload = {"provider": "firebase", "id_token": "tok"}
        if access_token:
            payload["access_token"] = access_token
        with patch.dict(os.environ, {"FIREBASE_PROJECT_ID": "mp-proj"}), patch(
            "google.oauth2.id_token.verify_firebase_token", return_value=claims, **kw
        ):
            return self._post(payload)

    @staticmethod
    def _firebase_claims(**over) -> dict:
        claims = {
            "iss": "https://securetoken.google.com/mp-proj",
            "aud": "mp-proj",
            "email": "fire@gmail.com",
            "email_verified": True,
            "name": "Fire Base User",
            "firebase": {"sign_in_provider": "google.com"},
        }
        claims.update(over)
        return claims

    def test_firebase_google_missing_email_filled_from_same_account(self):
        claims = self._firebase_claims(
            email="",
            email_verified=False,
            firebase={"sign_in_provider": "google.com", "identities": {"google.com": ["google-sub"]}},
        )
        info = {"sub": "google-sub", "email": "second@gmail.com", "email_verified": True, "given_name": "Second"}
        with patch("core.social_auth.requests.get", return_value=_resp(200, info)):
            resp = self._firebase(claims, access_token="ya29")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user"]["email"], "second@gmail.com")

    def test_firebase_google_missing_email_without_access_token(self):
        claims = self._firebase_claims(
            email="",
            firebase={"sign_in_provider": "google.com", "identities": {"google.com": ["google-sub"]}},
        )
        resp = self._firebase(claims)
        self.assertEqual(resp.json()["error"], "email_missing")

    def test_firebase_valid_token(self):
        resp = self._firebase(self._firebase_claims())
        self.assertEqual(resp.status_code, 200)
        user = resp.json()["user"]
        self.assertEqual((user["email"], user["first_name"], user["last_name"]), ("fire@gmail.com", "Fire", "Base User"))

    def test_firebase_same_email_same_account(self):
        existing = User.objects.create_user("fire", "fire@gmail.com", "pw-12345678")
        resp = self._firebase(self._firebase_claims())
        self.assertFalse(resp.json()["created"])
        self.assertEqual(resp.json()["user"]["id"], existing.id)

    def test_firebase_other_project_rejected(self):
        resp = self._firebase(self._firebase_claims(iss="https://securetoken.google.com/other"))
        self.assertEqual((resp.status_code, resp.json()["error"]), (401, "invalid_token"))

    def test_firebase_bad_signature(self):
        resp = self._firebase(side_effect=ValueError("bad"))
        self.assertEqual(resp.json()["error"], "invalid_token")

    def _github_claims(self) -> dict:
        return self._firebase_claims(
            email="unverified@else.com",
            email_verified=False,
            firebase={"sign_in_provider": "github.com", "identities": {"github.com": ["77"]}},
        )

    def test_firebase_github_token(self):
        def fake_get(url, **kw):
            if url.endswith("/user/emails"):
                return _resp(200, [{"email": "dev@example.com", "verified": True, "primary": True}])
            return _resp(200, {"id": 77, "name": "Dev Person"})

        with patch("core.social_auth.requests.get", side_effect=fake_get):
            resp = self._firebase(self._github_claims(), access_token="gh-token")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user"]["email"], "dev@example.com")

    def test_firebase_github_needs_access_token(self):
        resp = self._firebase(self._github_claims())
        self.assertEqual((resp.status_code, resp.json()["error"]), (400, "access_token_required"))

    def test_firebase_removed_providers_rejected(self):
        for provider in ("password", "facebook.com"):
            resp = self._firebase(self._firebase_claims(firebase={"sign_in_provider": provider}))
            self.assertEqual(resp.json()["error"], "unsupported_sign_in_provider")

    def test_firebase_not_configured(self):
        with patch.dict(os.environ, {"FIREBASE_PROJECT_ID": ""}):
            resp = self._post({"provider": "firebase", "id_token": "tok"})
        self.assertEqual((resp.status_code, resp.json()["error"]), (503, "not_configured"))

    def test_removed_native_providers_unknown(self):
        for provider in ("facebook", "linkedin", "github"):
            resp = self._post({"provider": provider, "access_token": "tok"})
            self.assertEqual((resp.status_code, resp.json()["error"]), (404, "unknown_provider"))

    def test_inactive_user_blocked(self):
        User.objects.create_user("off", "off@example.com", "pw-12345678", is_active=False)
        resp = self._google({"aud": "gid", "email": "off@example.com", "email_verified": True})
        self.assertEqual((resp.status_code, resp.json()["error"]), (403, "inactive"))
