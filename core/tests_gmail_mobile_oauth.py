from __future__ import annotations

import json
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core import gmail_mobile_oauth as mobile
from core.models import MailAccount

CLIENT_SECRET = json.dumps({"installed": {"client_id": "x", "client_secret": "y"}}).encode()


@override_settings(SITE_URL="https://mailpilot.example.com")
class ReturnToTests(SimpleTestCase):
    def test_allowlist(self) -> None:
        for ok in (
            "mailpilot://oauth/gmail",
            "exp://192.168.1.5:8081/--/oauth/gmail",
            "exps://u.expo.dev/oauth/gmail",
            "http://localhost:8081/oauth/gmail",
            "http://127.0.0.1:8081",
            "https://mailpilot.example.com/app/oauth",
        ):
            self.assertTrue(mobile.is_allowed_return_to(ok), ok)
        for bad in (
            "",
            "https://evil.example.com/",
            "http://localhost:8081.evil.com/",
            "https://mailpilot.example.com.evil.com/",
            "javascript:alert(1)",
        ):
            self.assertFalse(mobile.is_allowed_return_to(bad), bad)

    def test_with_query_keeps_existing_params(self) -> None:
        url = mobile.with_query("exp://host:8081/--/oauth/gmail?x=1", {"status": "ok", "account_id": 7})
        self.assertEqual(url, "exp://host:8081/--/oauth/gmail?x=1&status=ok&account_id=7")

    def test_app_scheme_redirect(self) -> None:
        res = mobile.AppSchemeRedirect("mailpilot://oauth/gmail?status=ok")
        self.assertEqual(res["Location"], "mailpilot://oauth/gmail?status=ok")


@override_settings(SECURE_SSL_REDIRECT=False)
class MobileGmailOAuthTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user("mob", "mob@example.com", "pw-12345678")
        self.gmail = MailAccount.objects.create(user=self.user, slot=1, transport=MailAccount.TRANSPORT_GMAIL)
        self.smtp = MailAccount.objects.create(user=self.user, slot=1, transport=MailAccount.TRANSPORT_SMTP)
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")

    def _authorize(self, **params):
        return self.api.get("/api/v1/gmail/oauth/authorize-url", params)

    def test_authorize_url_rejects_unknown_account_and_bad_return_to(self) -> None:
        other = User.objects.create_user("o", "o@example.com", "pw-12345678")
        other_acc = MailAccount.objects.create(user=other, slot=1, transport=MailAccount.TRANSPORT_GMAIL)
        rt = "mailpilot://oauth/gmail"
        self.assertEqual(self._authorize(account_id=other_acc.id, return_to=rt).status_code, 404)
        self.assertEqual(self._authorize(account_id=self.smtp.id, return_to=rt).status_code, 404)
        self.assertEqual(self._authorize(return_to=rt).status_code, 404)
        res = self._authorize(account_id=self.gmail.id, return_to="https://evil.example.com/")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"], "invalid_return_to")

    def test_authorize_url_requires_client_secret(self) -> None:
        with mock.patch("core.gmail_mobile_oauth.os.path.exists", return_value=False):
            res = self._authorize(account_id=self.gmail.id, return_to="mailpilot://oauth/gmail")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"], "client_secret_missing")

    def test_authorize_url_stores_state_for_account(self) -> None:
        flow = mock.Mock()
        flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x", "st-1")
        with mock.patch("core.gmail_mobile_oauth.os.path.exists", return_value=True), mock.patch(
            "core.gmail_mobile_oauth.build_flow", return_value=flow
        ) as build_flow:
            res = self._authorize(account_id=self.gmail.id, return_to="exp://10.0.2.2:8081/--/oauth/gmail")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["state"], "st-1")
        entry = mobile.pending("st-1")
        self.assertEqual(entry["user_id"], self.user.id)
        self.assertEqual(entry["account_id"], self.gmail.id)
        self.assertEqual(entry["return_to"], "exp://10.0.2.2:8081/--/oauth/gmail")
        redirect_uri = build_flow.call_args.args[1]
        self.assertTrue(redirect_uri.startswith("http"))
        self.assertEqual(entry["redirect_uri"], redirect_uri)

    def _pending(self, state: str = "st-2") -> None:
        cache.set(
            mobile.state_cache_key(state),
            {
                "user_id": self.user.id,
                "account_id": self.gmail.id,
                "return_to": "mailpilot://oauth/gmail",
                "redirect_uri": "http://testserver/api/gmail/oauth/callback",
            },
        )

    def test_callback_without_session_saves_token_and_returns_to_app(self) -> None:
        self._pending()
        with mock.patch("core.gmail_mobile_oauth.exchange_and_save", return_value="") as exchange:
            res = self.client.get("/api/gmail/oauth/callback", {"state": "st-2", "code": "c-1"})
        self.assertEqual(res.status_code, 302)
        loc = urlsplit(res["Location"])
        self.assertEqual(f"{loc.scheme}://{loc.netloc}{loc.path}", "mailpilot://oauth/gmail")
        self.assertEqual(parse_qs(loc.query), {"status": ["ok"], "account_id": [str(self.gmail.id)]})
        acc = exchange.call_args.args[0]
        self.assertEqual(acc.id, self.gmail.id)
        self.assertEqual(exchange.call_args.kwargs["code"], "c-1")
        self.assertIsNone(mobile.pending("st-2"))

    def test_callback_reports_errors_to_app(self) -> None:
        self._pending()
        res = self.client.get("/api/gmail/oauth/callback", {"state": "st-2", "error": "access_denied"})
        self.assertEqual(parse_qs(urlsplit(res["Location"]).query), {"status": ["error"], "error": ["access_denied"]})

        self._pending("st-3")
        with mock.patch("core.gmail_mobile_oauth.exchange_and_save", return_value="token_exchange_failed: bad"):
            res = self.client.get("/api/gmail/oauth/callback", {"state": "st-3", "code": "c"})
        query = parse_qs(urlsplit(res["Location"]).query)
        self.assertEqual(query["status"], ["error"])
        self.assertEqual(query["error"], ["token_exchange_failed: bad"])

    def test_callback_unknown_state_uses_web_flow(self) -> None:
        res = self.client.get("/api/gmail/oauth/callback", {"state": "nope", "code": "c"})
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login", res["Location"])

    def test_exchange_with_account_id_saves_on_mailbox(self) -> None:
        self._pending("st-4")
        with mock.patch("core.gmail_mobile_oauth.exchange_and_save", return_value="") as exchange:
            res = self.api.post(
                "/api/v1/gmail/oauth/exchange", {"code": "c", "state": "st-4", "account_id": self.gmail.id}, format="json"
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True, "account_id": self.gmail.id})
        self.assertEqual(exchange.call_args.kwargs["redirect_uri"], "http://testserver/api/gmail/oauth/callback")
        res = self.api.post("/api/v1/gmail/oauth/exchange", {"code": "c", "account_id": self.smtp.id}, format="json")
        self.assertEqual(res.status_code, 404)


@override_settings(SECURE_SSL_REDIRECT=False)
class WebGmailSetupTests(TestCase):
    """Browser (session) flow on /setup: errors come back to the setup page, never as raw JSON."""

    def setUp(self) -> None:
        self.user = User.objects.create_user("web", "web@example.com", "pw-12345678")
        self.gmail = MailAccount.objects.create(user=self.user, slot=1, transport=MailAccount.TRANSPORT_GMAIL)
        self.client.force_login(self.user)

    def test_mailbox_form_error_redirects_to_setup(self) -> None:
        res = self.client.post(
            f"/api/mail-accounts/{self.gmail.id}/setup-credentials",
            {"gmail_address": "me@gmail.com", "client_secret": SimpleUploadedFile("c.txt", CLIENT_SECRET)},
        )
        self.assertEqual(res.status_code, 302)
        loc = urlsplit(res["Location"])
        self.assertEqual(loc.path, "/setup")
        query = parse_qs(loc.query)
        self.assertIn("oauth_error", query)
        self.assertEqual(query["account_id"], [str(self.gmail.id)])

    def test_mailbox_form_success_starts_oauth(self) -> None:
        with mock.patch("core.mail_account_views.save_account_client_secret"):
            res = self.client.post(
                f"/api/mail-accounts/{self.gmail.id}/setup-credentials",
                {"gmail_address": "me@gmail.com", "client_secret": SimpleUploadedFile("c.json", CLIENT_SECRET)},
            )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res["Location"], "/api/gmail/oauth/start")
        self.assertEqual(self.client.session["oauth_account_id"], self.gmail.id)

    def test_oauth_start_without_client_secret_redirects_to_setup(self) -> None:
        with mock.patch("core.views.os.path.exists", return_value=False):
            res = self.client.get("/api/gmail/oauth/start")
        self.assertEqual(res.status_code, 302)
        self.assertIn("oauth_error=client_secret_missing", res["Location"])

    def test_disconnect_gmail_route(self) -> None:
        res = self.client.post(f"/api/mail-accounts/{self.gmail.id}/disconnect-gmail", "{}", content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})


@override_settings(SECURE_SSL_REDIRECT=False)
class MailboxCredentialsTests(TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("email_automation.gmail_auth.gmail_oauth_ready", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user("cred", "cred@example.com", "pw-12345678")
        self.gmail = MailAccount.objects.create(user=self.user, slot=1, transport=MailAccount.TRANSPORT_GMAIL)
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")

    def _upload(self, account_id: int, *, name: str = "client_secret.json", content: bytes = CLIENT_SECRET, address="me@gmail.com"):
        data = {"client_secret": SimpleUploadedFile(name, content, content_type="application/json")}
        if address:
            data["gmail_address"] = address
        return self.api.post(f"/api/v1/mail-accounts/{account_id}/setup-credentials", data, format="multipart")

    def test_per_mailbox_upload(self) -> None:
        with mock.patch("core.mail_account_views.save_account_client_secret") as save:
            res = self._upload(self.gmail.id)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["account"]["id"], self.gmail.id)
        self.assertEqual(body["account"]["config"]["GMAIL_ADDRESS"], "me@gmail.com")
        self.assertEqual(json.loads(save.call_args.args[1]), json.loads(CLIENT_SECRET))

    def test_per_mailbox_upload_validation(self) -> None:
        smtp = MailAccount.objects.create(user=self.user, slot=1, transport=MailAccount.TRANSPORT_SMTP)
        self.assertEqual(self._upload(smtp.id).status_code, 404)
        self.assertEqual(self._upload(99999).status_code, 404)
        self.assertEqual(self._upload(self.gmail.id, address="").status_code, 400)
        self.assertEqual(self._upload(self.gmail.id, name="secret.txt").status_code, 400)
        res = self._upload(self.gmail.id, content=b"not json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"], "client_secret is not valid JSON")

    def test_legacy_setup_credentials_returns_json(self) -> None:
        with mock.patch("core.mail_accounts.save_account_client_secret"), mock.patch(
            "core.user_settings.save_client_secret_json"
        ):
            res = self.api.post(
                "/api/v1/setup/credentials",
                {
                    "gmail_address": "me@gmail.com",
                    "client_secret": SimpleUploadedFile("client_secret.json", CLIENT_SECRET),
                },
                format="multipart",
            )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        self.assertEqual(res.json()["account"]["id"], self.gmail.id)

    def test_legacy_setup_credentials_plan_limit_is_403_not_500(self) -> None:
        from core.billing import GateResult

        self.gmail.delete()
        MailAccount.objects.create(user=self.user, slot=1, transport=MailAccount.TRANSPORT_SMTP)
        blocked = GateResult(False, "plan_inbox_limit_reached", {})
        with mock.patch("core.billing.can_enable_mailbox", return_value=blocked):
            res = self.api.post(
                "/api/v1/setup/credentials",
                {
                    "gmail_address": "me@gmail.com",
                    "client_secret": SimpleUploadedFile("client_secret.json", CLIENT_SECRET),
                },
                format="multipart",
            )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"], "plan_inbox_limit_reached")
        self.assertTrue(res.json()["upgrade_required"])
        self.assertFalse(MailAccount.objects.filter(user=self.user, transport=MailAccount.TRANSPORT_GMAIL).exists())

    def test_mail_account_detail_get_and_delete(self) -> None:
        res = self.api.get(f"/api/v1/mail-accounts/{self.gmail.id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["account"]["id"], self.gmail.id)
        self.assertEqual(self.api.get("/api/v1/mail-accounts/99999").status_code, 404)
        res = self.api.delete(f"/api/v1/mail-accounts/{self.gmail.id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})
        self.assertFalse(MailAccount.objects.filter(pk=self.gmail.id).exists())
