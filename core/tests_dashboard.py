from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.dashboard_stats import dashboard_summary
from core.models import MailAccount, ProcessedMeta, QueueItem, UserProfile


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@override_settings(SECURE_SSL_REDIRECT=False)
class DashboardSummaryTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user("dash", "dash@example.com", "pw-12345678")
        self.acc = MailAccount.objects.create(user=self.user, slot=1, transport=MailAccount.TRANSPORT_SMTP, label="Support")
        self.tenant = f"{self.user.id}:{self.acc.id}"
        self.now = datetime.now(timezone.utc)

    def _row(self, message_id: str, action: str, *, tenant: str | None = None, when: datetime | None = None, **extra) -> None:
        meta = {"action": action, "processed_at": _iso(when or self.now), "subject": f"Subject {message_id}", **extra}
        ProcessedMeta.objects.create(tenant_id=tenant or self.tenant, message_id=message_id, meta_json=meta)

    def test_counts_by_action_skip_aliases_and_thread_keys(self) -> None:
        self._row("m1", "sent")
        self._row("m2", "sent")
        self._row("m3", "draft")
        self._row("m4", "ignored")
        self._row("m5", "error")
        self._row("<rfc-m1@example.com>", "sent", canonical_id="m1")
        self._row("gthread:t1", "sent")
        self._row("m6", "processing")

        totals = dashboard_summary(self.user)["totals"]

        self.assertEqual(totals["processed"], 5)
        self.assertEqual(totals["sent"], 2)
        self.assertEqual(totals["drafts"], 1)
        self.assertEqual(totals["filtered"], 1)
        self.assertEqual(totals["failed"], 1)

    def test_breakdown_percentages(self) -> None:
        for i in range(3):
            self._row(f"s{i}", "sent")
        self._row("d1", "draft")

        breakdown = {b["key"]: b for b in dashboard_summary(self.user)["breakdown"]}

        self.assertEqual(breakdown["sent"]["percent"], 75)
        self.assertEqual(breakdown["drafts"]["percent"], 25)
        self.assertEqual(breakdown["failed"]["percent"], 0)

    def test_other_users_data_is_not_counted(self) -> None:
        other = User.objects.create_user("other", "other@example.com", "pw-12345678")
        other_acc = MailAccount.objects.create(user=other, slot=1, transport=MailAccount.TRANSPORT_SMTP)
        self._row("x1", "sent", tenant=f"{other.id}:{other_acc.id}")
        self._row("x2", "sent", tenant=str(other.id))
        self._row("mine", "draft")

        totals = dashboard_summary(self.user)["totals"]

        self.assertEqual(totals["processed"], 1)
        self.assertEqual(totals["sent"], 0)

    def test_daily_buckets_use_user_timezone(self) -> None:
        tz = ZoneInfo("Asia/Dhaka")
        UserProfile.objects.update_or_create(user=self.user, defaults={"timezone": "Asia/Dhaka"})
        local_midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        self._row("early", "sent", when=local_midnight + timedelta(hours=1))
        self._row("old", "sent", when=local_midnight - timedelta(days=10))

        data = dashboard_summary(self.user)
        daily = data["daily"]

        self.assertEqual(len(daily), 7)
        self.assertEqual(daily[-1]["date"], local_midnight.date().isoformat())
        self.assertEqual(daily[-1]["auto_replied"], 1)
        self.assertEqual(data["week_total"], 1)
        self.assertEqual(data["totals"]["processed"], 2)

    def test_recent_mailbox_health_and_pending(self) -> None:
        self._row("older", "draft", when=self.now - timedelta(hours=2), thread_id="t-old")
        self._row("newer", "sent", when=self.now - timedelta(minutes=5), thread_id="t-new", from_email="a@b.com")
        QueueItem.objects.create(tenant_id=self.tenant, message_id="q1", status="pending")
        QueueItem.objects.create(tenant_id=self.tenant, message_id="q2", status="sent")
        MailAccount.objects.create(user=self.user, slot=2, transport=MailAccount.TRANSPORT_SMTP, is_enabled=False)

        data = dashboard_summary(self.user)

        self.assertEqual([r["message_id"] for r in data["recent"]], ["newer", "older"])
        self.assertEqual(data["recent"][0]["thread_id"], "t-new")
        self.assertEqual(data["recent"][0]["account_id"], self.acc.id)
        self.assertEqual(data["totals"]["pending"], 1)
        self.assertIsNotNone(data["totals"]["latest_processed_at"])
        items = {m["id"]: m for m in data["mailboxes"]["items"]}
        self.assertEqual(data["mailboxes"]["total"], 2)
        self.assertEqual(data["mailboxes"]["connected"], 0)
        self.assertEqual(items[self.acc.id]["processed"], 2)
        self.assertEqual(items[self.acc.id]["status"], "needs_setup")
        self.assertIn("disabled", {m["status"] for m in items.values()})


@override_settings(SECURE_SSL_REDIRECT=False)
class DashboardEndpointTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user("dash2", "dash2@example.com", "pw-12345678")

    def test_session_api_requires_login(self) -> None:
        res = self.client.get("/api/dashboard/summary")
        self.assertEqual(res.status_code, 401)

    def test_session_api_returns_summary(self) -> None:
        self.client.force_login(self.user)
        res = self.client.get("/api/dashboard/summary")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        for key in ("mailboxes", "totals", "breakdown", "daily", "recent", "usage", "plan"):
            self.assertIn(key, body)

    def test_v1_api_uses_jwt(self) -> None:
        api = APIClient()
        self.assertEqual(api.get("/api/v1/dashboard/summary").status_code, 401)
        token = str(RefreshToken.for_user(self.user).access_token)
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        res = api.get("/api/v1/dashboard/summary?days=7")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        self.assertEqual(len(res.json()["daily"]), 7)

    def test_dashboard_and_inbox_pages_render(self) -> None:
        self.client.force_login(self.user)
        dash = self.client.get("/dashboard")
        self.assertEqual(dash.status_code, 200)
        self.assertTemplateUsed(dash, "dashboard.html")
        self.assertContains(dash, 'id="ovData"')
        inbox = self.client.get("/inbox")
        self.assertEqual(inbox.status_code, 200)
        self.assertTemplateUsed(inbox, "inbox.html")

    def test_pages_require_login(self) -> None:
        self.assertEqual(self.client.get("/dashboard").status_code, 302)
        self.assertEqual(self.client.get("/inbox").status_code, 302)
