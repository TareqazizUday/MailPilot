from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from mailpilot.env import env_flag, production_problems, resolve_env, site_hosts


class ResolveEnvTests(SimpleTestCase):
    def test_explicit_switch_wins(self):
        self.assertEqual(resolve_env({"MAILPILOT_ENV": "production", "DJANGO_DEBUG": "true"}), ("production", True))
        self.assertEqual(resolve_env({"MAILPILOT_ENV": "LOCAL", "DJANGO_DEBUG": "false"}), ("local", True))

    def test_legacy_debug_rule(self):
        self.assertEqual(resolve_env({"DJANGO_DEBUG": "false"}), ("production", False))
        self.assertEqual(resolve_env({"FLASK_DEBUG": "0"}), ("production", False))
        self.assertEqual(resolve_env({}), ("local", False))
        self.assertEqual(resolve_env({"DJANGO_DEBUG": "false"}, runserver=True), ("local", False))
        self.assertEqual(resolve_env({"MAILPILOT_ENV": "staging"}), ("local", False))

    def test_env_flag(self):
        self.assertIs(env_flag("X", {"X": "Yes"}), True)
        self.assertIs(env_flag("X", {"X": "0"}), False)
        self.assertIsNone(env_flag("X", {"X": " "}))
        self.assertIsNone(env_flag("X", {}))


class SiteHostsTests(SimpleTestCase):
    def test_bare_and_www_twin(self):
        self.assertEqual(site_hosts("https://mailpilots.net"), ["mailpilots.net", "www.mailpilots.net"])
        self.assertEqual(site_hosts("https://www.mailpilots.net/"), ["www.mailpilots.net", "mailpilots.net"])

    def test_local_addresses_have_no_twin(self):
        self.assertEqual(site_hosts("http://127.0.0.1:8000"), ["127.0.0.1"])
        self.assertEqual(site_hosts("http://localhost:8000"), ["localhost"])
        self.assertEqual(site_hosts(""), [])


class ProductionProblemsTests(SimpleTestCase):
    def test_good_config(self):
        self.assertEqual(production_problems(secret_key="x" * 60, site_url="https://mailpilots.net"), [])

    def test_dev_secret_and_missing_site(self):
        problems = production_problems(secret_key="dev-email-automation-secret", site_url="")
        self.assertEqual(len(problems), 2)

    def test_http_site_rejected(self):
        self.assertIn("https", production_problems(secret_key="x" * 60, site_url="http://mailpilots.net")[0])


_PROD_HTTP = dict(
    DEBUG=False,
    ALLOWED_HOSTS=["127.0.0.1", "localhost", "mailpilots.net", "www.mailpilots.net"],
    SECURE_SSL_REDIRECT=True,
    SECURE_REDIRECT_EXEMPT=[r"^healthz$"],
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
    USE_X_FORWARDED_HOST=True,
)


@override_settings(**_PROD_HTTP)
class ProductionRequestTests(TestCase):
    def test_plain_http_redirects_to_https(self):
        resp = self.client.get("/login", HTTP_HOST="mailpilots.net")
        self.assertEqual((resp.status_code, resp["Location"]), (301, "https://mailpilots.net/login"))

    def test_loopback_health_check_not_redirected(self):
        self.assertEqual(self.client.get("/healthz", HTTP_HOST="127.0.0.1:8011").status_code, 200)

    def test_proxied_https_request_served_with_secure_csrf_cookie(self):
        resp = self.client.get("/login", HTTP_HOST="mailpilots.net", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.cookies["csrftoken"]["secure"])

    def test_www_and_unknown_hosts(self):
        www = self.client.get("/healthz", HTTP_HOST="www.mailpilots.net", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(www.status_code, 200)
        evil = self.client.get("/login", HTTP_HOST="evil.example", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(evil.status_code, 400)


class DeployCheckCommandTests(TestCase):
    def test_local_run_passes(self):
        out = StringIO()
        call_command("deploy_check", "--skip-billing", stdout=out)
        self.assertIn("Deploy check", out.getvalue())

    @override_settings(DEBUG=True, SITE_URL="", MAILPILOT_ENV="local", IS_PRODUCTION=False)
    def test_strict_run_fails_on_local_config(self):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("deploy_check", "--production", "--skip-billing", stdout=out)
        self.assertIn("FAIL", out.getvalue())
