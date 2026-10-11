from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import MailAccount

CLIENT_SECRET = json.dumps({"installed": {"client_id": "x", "client_secret": "y"}}).encode()


@override_settings(SECURE_SSL_REDIRECT=False)
class V1SmokeTests(TestCase):
    """Every v1 endpoint answers with JSON and never a 5xx for ordinary input."""

    def setUp(self) -> None:
        patcher = mock.patch("email_automation.gmail_auth.gmail_oauth_ready", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user("smoke", "smoke@example.com", "pw-12345678")
        self.gmail = MailAccount.objects.create(user=self.user, slot=1, transport=MailAccount.TRANSPORT_GMAIL)
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")

    def _assert_ok(self, res, label: str) -> None:
        self.assertLess(res.status_code, 500, f"{label} -> {res.status_code}: {res.content[:300]!r}")
        self.assertEqual(res["Content-Type"].split(";")[0], "application/json", label)

    def test_get_endpoints(self) -> None:
        aid = self.gmail.id
        for path in (
            "/api/v1/me",
            "/api/v1/pricing",
            "/api/v1/billing/summary",
            "/api/v1/dashboard/summary",
            "/api/v1/mail-accounts",
            f"/api/v1/mail-accounts/{aid}",
            f"/api/v1/gmail/connection-status?account_id={aid}",
            f"/api/v1/gmail/inbox?account_id={aid}",
            f"/api/v1/gmail/threads/missing?account_id={aid}",
            "/api/v1/pending",
            "/api/v1/smtp/status",
            "/api/v1/telegram/status",
            "/api/v1/whatsapp/status",
            "/api/v1/kb/crawl/status",
        ):
            self._assert_ok(self.api.get(path), path)

    def test_post_endpoints_with_empty_or_invalid_input(self) -> None:
        aid = self.gmail.id
        for path, body in (
            ("/api/v1/me/change-password", {"current_password": "wrong", "new_password": "x"}),
            ("/api/v1/gmail/oauth/exchange", {}),
            ("/api/v1/billing/select-plan", {"plan": "nope"}),
            ("/api/v1/transport-mode", {"mode": "nope"}),
            ("/api/v1/mail-accounts/create", {"transport": "nope"}),
            (f"/api/v1/mail-accounts/{aid}/test-smtp", {}),
            ("/api/v1/telegram/config", {}),
            ("/api/v1/whatsapp/config", {}),
        ):
            self._assert_ok(self.api.post(path, body, format="json"), path)

    def test_setup_credentials_variants(self) -> None:
        def upload():
            return {"gmail_address": "me@gmail.com", "client_secret": SimpleUploadedFile("c.json", CLIENT_SECRET)}

        with mock.patch("core.mail_accounts.save_account_client_secret"), mock.patch(
            "core.user_settings.save_client_secret_json"
        ), mock.patch("core.mail_account_views.save_account_client_secret"):
            self._assert_ok(self.api.post("/api/v1/setup/credentials", upload(), format="multipart"), "setup")
            path = f"/api/v1/mail-accounts/{self.gmail.id}/setup-credentials"
            self._assert_ok(self.api.post(path, upload(), format="multipart"), path)
            self._assert_ok(self.api.post("/api/v1/setup/credentials", {}, format="multipart"), "setup empty")

    def test_docs_urls_without_trailing_slash_redirect(self) -> None:
        for path in ("/api/docs", "/api/redoc", "/api/schema"):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 302, path)
            self.assertEqual(res["Location"], path + "/")
        self.assertEqual(self.client.get("/api/docs/").status_code, 200)

    def test_unauthenticated_is_401_json(self) -> None:
        anon = APIClient()
        for path in ("/api/v1/me", "/api/v1/mail-accounts", "/api/v1/dashboard/summary", "/api/v1/billing/summary"):
            res = anon.get(path)
            self.assertEqual(res.status_code, 401, path)
            self.assertEqual(res["Content-Type"].split(";")[0], "application/json", path)
