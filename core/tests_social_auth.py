from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

_KEYS = {
    "GOOGLE_LOGIN_CLIENT_ID": "gid",
    "GOOGLE_LOGIN_CLIENT_SECRET": "gsecret",
}
_NO_KEYS = {k: "" for k in _KEYS}


def _resp(status: int, data) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data
    return r


@override_settings(SECURE_SSL_REDIRECT=False)
class SocialAuthTests(TestCase):
    def _start(self, button: str, **params):
        resp = self.client.get(f"/auth/social/{button}/start", params)
        self.assertEqual(resp.status_code, 302)
        return resp

    def _callback(self, provider: str, profile: dict, *, button: str | None = None, token_status=200):
        start = self._start(button or provider)
        state = parse_qs(urlparse(start["Location"]).query)["state"][0]
        with patch("core.social_auth.requests.post", return_value=_resp(token_status, {"access_token": "t"})), patch(
            "core.social_auth.requests.get",
            side_effect=lambda url, **kw: _resp(200, {"access_token": "t"})
            if "access_token" in url
            else _resp(200, profile),
        ):
            return self.client.get(f"/auth/social/{provider}/callback", {"state": state, "code": "abc"})

    def test_pages_render_social_buttons(self):
        for page in ("/login", "/signup"):
            html = self.client.get(page).content.decode()
            for name in ("Google", "GitHub"):
                self.assertIn(f'aria-label="Continue with {name}"', html)
            for gone in ("Facebook", "LinkedIn", "Gmail"):
                self.assertNotIn(f'aria-label="Continue with {gone}"', html)

    @patch.dict(os.environ, _NO_KEYS)
    def test_unconfigured_provider_shows_message(self):
        resp = self._start("google", **{"from": "signup"})
        self.assertTrue(resp["Location"].startswith("/signup?"))
        page = self.client.get(resp["Location"]).content.decode()
        self.assertIn("Google sign-in is not available yet", page)

    def test_github_message_label(self):
        page = self.client.get("/login?social_error=not_configured&provider=github").content.decode()
        self.assertIn("GitHub sign-in is not available yet", page)

    def test_unknown_button_404(self):
        for button in ("twitter", "gmail", "facebook", "linkedin", "github"):
            self.assertEqual(self.client.get(f"/auth/social/{button}/start").status_code, 404)

    @patch.dict(os.environ, _KEYS)
    def test_start_redirects_to_provider(self):
        loc = urlparse(self._start("google")["Location"])
        self.assertEqual(loc.netloc, "accounts.google.com")
        q = parse_qs(loc.query)
        self.assertEqual(q["client_id"], ["gid"])
        self.assertTrue(q["redirect_uri"][0].endswith("/auth/social/google/callback"))
        self.assertTrue(q["state"][0])

    @patch.dict(os.environ, _KEYS)
    def test_google_creates_user_and_logs_in(self):
        resp = self._callback(
            "google",
            {"email": "New.Person@Example.com", "email_verified": True, "given_name": "New", "family_name": "Person"},
        )
        self.assertEqual(resp["Location"], "/dashboard")
        user = User.objects.get(email="new.person@example.com")
        self.assertEqual((user.first_name, user.last_name), ("New", "Person"))
        self.assertFalse(user.has_usable_password())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    @patch.dict(os.environ, _KEYS)
    def test_existing_email_logs_into_same_account(self):
        user = User.objects.create_user("owner", "owner@example.com", "pw-12345678")
        self._callback("google", {"email": "OWNER@example.com", "email_verified": True})
        self.assertEqual(User.objects.filter(email__iexact="owner@example.com").count(), 1)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    @patch.dict(os.environ, _KEYS)
    def test_unverified_email_rejected(self):
        resp = self._callback("google", {"email": "x@example.com", "email_verified": False})
        self.assertIn("social_error=email_unverified", resp["Location"])
        self.assertFalse(User.objects.filter(email="x@example.com").exists())

    @patch.dict(os.environ, _KEYS)
    def test_google_accepts_gmail_address(self):
        self._callback("google", {"email": "me@gmail.com", "email_verified": True})
        self.assertTrue(User.objects.filter(email="me@gmail.com").exists())

    @patch.dict(os.environ, _KEYS)
    def test_state_mismatch_rejected(self):
        self._start("google")
        resp = self.client.get("/auth/social/google/callback", {"state": "wrong", "code": "abc"})
        self.assertIn("social_error=state_mismatch", resp["Location"])

    @patch.dict(os.environ, _KEYS)
    def test_cancelled_by_user(self):
        start = self._start("google")
        state = parse_qs(urlparse(start["Location"]).query)["state"][0]
        resp = self.client.get("/auth/social/google/callback", {"state": state, "error": "access_denied"})
        self.assertIn("social_error=cancelled", resp["Location"])

    @patch.dict(os.environ, _KEYS)
    def test_token_failure_is_reported(self):
        resp = self._callback("google", {}, token_status=400)
        self.assertIn("social_error=failed", resp["Location"])

    @patch.dict(os.environ, _KEYS)
    def test_inactive_user_blocked(self):
        User.objects.create_user("off", "off@example.com", "pw-12345678", is_active=False)
        resp = self._callback("google", {"email": "off@example.com", "email_verified": True})
        self.assertIn("social_error=inactive", resp["Location"])

    def test_unknown_error_code_ignored(self):
        html = self.client.get("/login?social_error=<script>&provider=google").content.decode()
        self.assertNotIn('class="err"', html)


_FIREBASE = {
    "FIREBASE_PROJECT_ID": "mp-proj",
    "FIREBASE_API_KEY": "web-key",
    "FIREBASE_AUTH_DOMAIN": "",
    "FIREBASE_APP_ID": "1:2:web:3",
}


def _firebase_claims(**over) -> dict:
    claims = {
        "iss": "https://securetoken.google.com/mp-proj",
        "aud": "mp-proj",
        "email": "web@gmail.com",
        "email_verified": True,
        "name": "Web User",
        "firebase": {"sign_in_provider": "google.com"},
    }
    claims.update(over)
    return claims


def _github_claims(**over) -> dict:
    """Firebase GitHub token: email (if any) is never marked verified."""
    return _firebase_claims(
        email="maybe@else.com",
        email_verified=False,
        name="",
        firebase={"sign_in_provider": "github.com", "identities": {"github.com": ["4242"]}},
        **over,
    )


def _github_api(*, user_id=4242, emails=None, emails_status=200):
    """Patch GitHub's /user and /user/emails as called by ``core.social_auth``."""
    if emails is None:
        emails = [
            {"email": "old@example.com", "verified": True, "primary": False},
            {"email": "Git@Example.com", "verified": True, "primary": True},
        ]

    def fake_get(url, **kw):
        assert kw["headers"]["Authorization"] == "Bearer gh-token"
        if url.endswith("/user/emails"):
            return _resp(emails_status, emails)
        return _resp(200, {"id": user_id, "name": "Git Hubber"})

    return patch("core.social_auth.requests.get", side_effect=fake_get)


@override_settings(SECURE_SSL_REDIRECT=False)
@patch.dict(os.environ, {**_KEYS, **_FIREBASE})
class FirebaseWebLoginTests(TestCase):
    def _post(self, claims=None, *, client=None, **body):
        payload = {"id_token": "tok", **body}
        with patch("google.oauth2.id_token.verify_firebase_token", return_value=claims):
            return (client or self.client).post("/auth/social/firebase", payload, content_type="application/json")

    def test_pages_include_firebase_config(self):
        for page in ("/login", "/signup"):
            html = self.client.get(page).content.decode()
            self.assertIn('id="firebase-web-config"', html)
            self.assertIn("mp-proj.firebaseapp.com", html)
            self.assertIn('data-firebase-provider="google"', html)
            self.assertIn("/auth/social/github/start", html)
            self.assertNotIn('data-firebase-provider="github"', html)

    @patch.dict(os.environ, {"FIREBASE_API_KEY": ""})
    def test_no_firebase_keeps_redirect_flow(self):
        html = self.client.get("/login").content.decode()
        self.assertNotIn("firebase-web-config", html)
        self.assertIn("/auth/social/google/start", html)
        self.assertIn("social_error=not_configured&amp;provider=github", html)

    def test_popup_token_logs_in(self):
        resp = self._post(_firebase_claims(), next="/inbox")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((resp.json()["ok"], resp.json()["redirect"]), (True, "/inbox"))
        user = User.objects.get(email="web@gmail.com")
        self.assertEqual((user.first_name, user.last_name), ("Web", "User"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.id)

    def test_existing_email_same_account(self):
        existing = User.objects.create_user("web", "web@gmail.com", "pw-12345678")
        resp = self._post(_firebase_claims())
        self.assertFalse(resp.json()["created"])
        self.assertEqual(int(self.client.session["_auth_user_id"]), existing.id)

    def test_external_next_ignored(self):
        resp = self._post(_firebase_claims(), next="https://evil.example/x")
        self.assertEqual(resp.json()["redirect"], "/dashboard")

    def test_other_project_rejected(self):
        resp = self._post(_firebase_claims(iss="https://securetoken.google.com/other"), **{"from": "signup"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["redirect"], "/signup?social_error=invalid_token&provider=google")
        self.assertNotIn("_auth_user_id", self.client.session)
        page = self.client.get(resp.json()["redirect"]).content.decode()
        self.assertIn("Could not verify your Google sign-in", page)

    def test_unverified_email_rejected(self):
        resp = self._post(_firebase_claims(email_verified=False))
        self.assertEqual(resp.json()["error"], "email_unverified")

    def test_github_uses_verified_primary_email_from_github(self):
        existing = User.objects.create_user("git", "git@example.com", "pw-12345678")
        with _github_api():
            resp = self._post(_github_claims(), provider="github", access_token="gh-token")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["created"])
        self.assertEqual(int(self.client.session["_auth_user_id"]), existing.id)
        self.assertFalse(User.objects.filter(email="maybe@else.com").exists())

    def test_github_new_user_gets_github_name(self):
        with _github_api():
            self._post(_github_claims(), provider="github", access_token="gh-token")
        user = User.objects.get(email="git@example.com")
        self.assertEqual((user.first_name, user.last_name), ("Git", "Hubber"))

    def test_github_requires_access_token(self):
        resp = self._post(_github_claims(), provider="github")
        self.assertEqual(resp.json()["error"], "access_token_required")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_github_token_for_other_account_rejected(self):
        with _github_api(user_id=9999):
            resp = self._post(_github_claims(), provider="github", access_token="gh-token")
        self.assertEqual(resp.json()["error"], "invalid_token")

    def test_github_without_verified_email_rejected(self):
        emails = [{"email": "victim@example.com", "verified": False, "primary": True}]
        User.objects.create_user("victim", "victim@example.com", "pw-12345678")
        with _github_api(emails=emails):
            resp = self._post(_github_claims(), provider="github", access_token="gh-token", **{"from": "signup"})
        self.assertEqual(resp.json()["redirect"], "/signup?social_error=email_unverified&provider=github")
        self.assertNotIn("_auth_user_id", self.client.session)
        page = self.client.get(resp.json()["redirect"]).content.decode()
        self.assertIn("Your GitHub email address is not verified", page)

    def test_github_with_no_email_rejected(self):
        with _github_api(emails=[]):
            resp = self._post(_github_claims(), provider="github", access_token="gh-token")
        self.assertEqual(resp.json()["error"], "email_missing")

    def test_github_emails_api_failure(self):
        with _github_api(emails_status=403):
            resp = self._post(_github_claims(), provider="github", access_token="gh-token")
        self.assertEqual(resp.json()["error"], "failed")

    def test_removed_providers_rejected(self):
        for provider in ("facebook.com", "password", "linkedin.com"):
            resp = self._post(_firebase_claims(firebase={"sign_in_provider": provider}))
            self.assertEqual(resp.json()["error"], "unsupported_sign_in_provider")

    def test_requires_csrf(self):
        from django.test import Client

        resp = self._post(_firebase_claims(), client=Client(enforce_csrf_checks=True))
        self.assertEqual(resp.status_code, 403)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get("/auth/social/firebase").status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
@patch.dict(os.environ, {**_KEYS, **_FIREBASE})
class FirebaseAppBrowserTests(TestCase):
    """Expo Go / GitHub in the app: in-app browser page -> Firebase popup -> one-time code deep link."""

    _RETURN = "exp://10.0.0.5:8081/--/auth/social"

    def _post(self, claims=None, *, return_to=_RETURN, **body):
        with patch("google.oauth2.id_token.verify_firebase_token", return_value=claims):
            return self.client.post(
                "/auth/social/firebase/app",
                {"id_token": "tok", "return_to": return_to, **body},
                content_type="application/json",
            )

    def test_page_renders_button(self):
        html = self.client.get("/auth/social/firebase/app", {"return_to": self._RETURN}).content.decode()
        self.assertIn('id="provider-btn"', html)
        self.assertIn("Continue with Google", html)
        self.assertIn("mp-proj.firebaseapp.com", html)

    def test_page_github_button(self):
        html = self.client.get(
            "/auth/social/firebase/app", {"return_to": self._RETURN, "provider": "github"}
        ).content.decode()
        self.assertIn("Continue with GitHub", html)
        self.assertIn("GithubAuthProvider", html)

    def test_page_unknown_provider_defaults_to_google(self):
        for provider in ("<x>", "facebook"):
            html = self.client.get(
                "/auth/social/firebase/app", {"return_to": self._RETURN, "provider": provider}
            ).content.decode()
            self.assertIn("Continue with Google", html)

    def test_page_has_return_link_for_custom_tabs(self):
        html = self.client.get(
            "/auth/social/firebase/app", {"return_to": "mailpilot://social", "provider": "github"}
        ).content.decode()
        self.assertIn('id="return-link"', html)
        self.assertIn("Open MailPilot", html)
        self.assertIn("signInWithRedirect", html)
        self.assertIn("getRedirectResult", html)

    def test_page_rejects_bad_return_to(self):
        html = self.client.get("/auth/social/firebase/app", {"return_to": "https://evil.example/x"}).content.decode()
        self.assertNotIn('id="provider-btn"', html)
        self.assertNotIn('id="return-link"', html)
        self.assertIn("invalid", html)

    def test_github_token_deep_link_says_github(self):
        with _github_api():
            resp = self._post(_github_claims(), provider="github", access_token="gh-token")
        q = parse_qs(urlparse(resp.json()["redirect"]).query)
        self.assertEqual((q["status"][0], q["provider"][0]), ("ok", "github"))

    def test_token_returns_deep_link_with_code_that_redeems(self):
        resp = self._post(_firebase_claims())
        self.assertEqual(resp.status_code, 200)
        link = urlparse(resp.json()["redirect"])
        self.assertEqual(f"{link.scheme}://{link.netloc}{link.path}", self._RETURN)
        q = parse_qs(link.query)
        self.assertEqual((q["status"][0], q["provider"][0]), ("ok", "google"))

        tokens = self.client.post(
            "/api/v1/auth/social/exchange", {"code": q["code"][0]}, content_type="application/json"
        ).json()
        self.assertTrue(tokens["access"] and tokens["created"])
        self.assertEqual(tokens["user"]["email"], "web@gmail.com")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_bad_token_deep_links_error(self):
        resp = self._post(_firebase_claims(iss="https://securetoken.google.com/other"))
        q = parse_qs(urlparse(resp.json()["redirect"]).query)
        self.assertEqual((q["status"][0], q["error"][0]), ("error", "invalid_token"))

    def test_external_return_to_rejected(self):
        resp = self._post(_firebase_claims(), return_to="https://evil.example/cb")
        self.assertEqual((resp.status_code, resp.json()["error"]), (400, "invalid_return_to"))
        self.assertFalse(User.objects.filter(email="web@gmail.com").exists())
