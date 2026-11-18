"""Shared Gmail client + Microsoft Graph transport smoke tests."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from core.mail_accounts import (
    TRANSPORT_GMAIL,
    TRANSPORT_MICROSOFT,
    account_to_dict,
    build_effective_settings,
    create_account,
    has_shared_gmail_oauth_client,
    resolve_gmail_client_secret_path,
    shared_gmail_client_secret_path,
    update_shared_gmail_client_secret_value,
)
from core.models import MailAccount
from email_automation.microsoft_auth import microsoft_oauth_ready
from email_automation.worker import _send_reply_via_transport


def _minimal_web_client_secret() -> str:
    return json.dumps(
        {
            "web": {
                "client_id": "test-client.apps.googleusercontent.com",
                "project_id": "test",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": "test-secret",
                "redirect_uris": ["http://127.0.0.1:8000/api/gmail/oauth/callback"],
            }
        }
    )


class SharedGmailClientTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user("oauth_user", "oauth@example.com", "pw-12345678")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.secret_path = Path(self._tmpdir.name) / "shared_client.json"
        self.secret_path.write_text(_minimal_web_client_secret(), encoding="utf-8")

    def test_shared_client_path_and_effective_settings(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "GOOGLE_CLIENT_SECRET_FILE": str(self.secret_path),
                "GMAIL_OAUTH_CLIENT_SECRET_FILE": "",
                "GOOGLE_OAUTH_CLIENT_ID": "",
                "GOOGLE_OAUTH_CLIENT_SECRET": "",
                "GMAIL_OAUTH_CLIENT_ID": "",
                "GMAIL_OAUTH_CLIENT_SECRET": "",
            },
            clear=False,
        ):
            self.assertTrue(has_shared_gmail_oauth_client())
            self.assertEqual(shared_gmail_client_secret_path(), str(self.secret_path))
            acc = create_account(self.user, transport=TRANSPORT_GMAIL)
            settings = build_effective_settings(self.user, account_id=acc.id)
            self.assertEqual(settings.GOOGLE_CLIENT_SECRET_FILE, str(self.secret_path))
            d = account_to_dict(acc)
            self.assertTrue(d.get("shared_gmail_oauth") or d.get("has_client_secret"))

    def test_shared_client_from_env_vars(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "GOOGLE_OAUTH_CLIENT_ID": "env-client.apps.googleusercontent.com",
                "GOOGLE_OAUTH_CLIENT_SECRET": "GOCSPX-env-secret",
                "GOOGLE_CLIENT_SECRET_FILE": str(Path(self._tmpdir.name) / "missing.json"),
                "GMAIL_OAUTH_CLIENT_SECRET_FILE": "",
            },
            clear=False,
        ):
            self.assertTrue(has_shared_gmail_oauth_client())
            from core.gmail_oauth_client import shared_gmail_oauth_client_config

            cfg = shared_gmail_oauth_client_config()
            self.assertEqual(cfg["web"]["client_id"], "env-client.apps.googleusercontent.com")
            acc = create_account(self.user, transport=TRANSPORT_GMAIL)
            d = account_to_dict(acc)
            self.assertTrue(d.get("shared_gmail_oauth"))

    def test_update_shared_client_secret_value(self) -> None:
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_SECRET_FILE": str(self.secret_path)}, clear=False):
            ok, err = update_shared_gmail_client_secret_value("GOCSPX-rotated-for-test-xx")
            self.assertTrue(ok, err)
            data = json.loads(self.secret_path.read_text(encoding="utf-8"))
            self.assertEqual(data["web"]["client_secret"], "GOCSPX-rotated-for-test-xx")

    def test_byo_secret_wins_over_shared(self) -> None:
        acc = create_account(self.user, transport=TRANSPORT_GMAIL)
        byo = {
            "web": {
                "client_id": "byo-client.apps.googleusercontent.com",
                "client_secret": "byo-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://127.0.0.1:8000/api/gmail/oauth/callback"],
            }
        }
        from core.mail_accounts import save_account_client_secret

        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_SECRET_FILE": str(self.secret_path)}, clear=False):
            save_account_client_secret(acc, json.dumps(byo))
            acc.refresh_from_db()
            path = resolve_gmail_client_secret_path(self.user.id, acc)
            self.assertNotEqual(path, str(self.secret_path))
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(data["web"]["client_id"], "byo-client.apps.googleusercontent.com")

    def test_connect_oauth_redirects_when_shared_client_present(self) -> None:
        acc = create_account(self.user, transport=TRANSPORT_GMAIL)
        client = Client()
        client.force_login(self.user)
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_SECRET_FILE": str(self.secret_path)}, clear=False):
            with mock.patch("google_auth_oauthlib.flow.Flow.from_client_secrets_file") as flow_factory:
                flow = mock.Mock()
                flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", "state123")
                flow_factory.return_value = flow
                res = client.post(f"/api/mail-accounts/{acc.id}/connect-oauth")
                self.assertIn(res.status_code, (302, 303))
                self.assertIn("/api/gmail/oauth/start", res["Location"])
                res2 = client.get(res["Location"])
        self.assertIn(res2.status_code, (302, 303))
        self.assertIn("accounts.google.com", res2["Location"])


class MicrosoftTransportTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user("ms_user", "ms@example.com", "pw-12345678")

    def test_create_microsoft_account(self) -> None:
        acc = create_account(self.user, transport=TRANSPORT_MICROSOFT)
        self.assertEqual(acc.transport, MailAccount.TRANSPORT_MICROSOFT)
        d = account_to_dict(acc)
        self.assertEqual(d["transport"], "microsoft_graph")
        self.assertFalse(d["microsoft_connected"])

    def test_microsoft_oauth_ready_with_token_file(self) -> None:
        acc = create_account(self.user, transport=TRANSPORT_MICROSOFT)
        settings = build_effective_settings(self.user, account_id=acc.id)
        self.assertFalse(microsoft_oauth_ready(settings))
        path = settings.GOOGLE_TOKEN_FILE
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"access_token": "x", "refresh_token": "y"}, f)
        self.assertTrue(microsoft_oauth_ready(settings))

    def test_send_reply_uses_microsoft_client(self) -> None:
        client = mock.Mock()
        client.send_reply.return_value = "msg-1"
        settings = mock.Mock()
        settings.SEND_TRANSPORT = "microsoft_graph"
        out = _send_reply_via_transport(
            settings=settings,
            gmail_client=client,
            to_email="a@b.com",
            subject="Re: hi",
            body_text="hello",
            thread_id="conv-1",
        )
        self.assertEqual(out, "msg-1")
        client.send_reply.assert_called_once()

    @override_settings(ROOT_URLCONF="mailpilot.urls")
    def test_connect_oauth_requires_microsoft_config(self) -> None:
        acc = create_account(self.user, transport=TRANSPORT_MICROSOFT)
        client = Client()
        client.force_login(self.user)
        with mock.patch.dict(
            os.environ,
            {"MICROSOFT_OAUTH_CLIENT_ID": "", "MICROSOFT_OAUTH_CLIENT_SECRET": ""},
            clear=False,
        ):
            res = client.post(f"/api/mail-accounts/{acc.id}/connect-oauth")
        self.assertIn(res.status_code, (302, 303))
        self.assertIn("oauth_error", res["Location"])
        self.assertIn("microsoft_oauth_not_configured", res["Location"])
