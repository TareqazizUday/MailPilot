from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import MailAccount, Notification, PushDevice, UserProfile
from core.notifications import notify_mail_event
from core.notifications.delivery import cleanup_old_notifications, flush_digests, in_quiet_hours
from core.notifications.preferences import save_preferences

TOKEN = "ExponentPushToken[abc123]"


def _expo_response(tickets):
    resp = mock.Mock()
    resp.ok = True
    resp.status_code = 200
    resp.content = b"x"
    resp.json.return_value = {"data": tickets}
    return resp


@override_settings(NOTIFY_DELIVERY_SYNC=True, NOTIFY_EXTERNAL_RATE_LIMIT=10)
class NotificationRoutingTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user("notif", "notif@example.com", "pw-12345678")
        self.account = MailAccount.objects.create(user=self.user, slot=1, transport=MailAccount.TRANSPORT_GMAIL)
        self.tenant = f"{self.user.pk}:{self.account.pk}"
        self.telegram = self._patch("core.notifications.channels.telegram.send", return_value="sent")
        self.whatsapp = self._patch("core.notifications.channels.whatsapp.send", return_value="not_configured")
        self.post = self._patch("core.notifications.channels.expo_push.requests.post")

    def _patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def _emit(self, event="draft", message_id="m1", **kwargs) -> Notification | None:
        with self.captureOnCommitCallbacks(execute=True):
            n = notify_mail_event(
                self.tenant,
                event,
                subject="Pricing question",
                from_email="client@example.com",
                message_id=message_id,
                thread_id="t1",
                **kwargs,
            )
        if n is not None:
            n.refresh_from_db()
        return n

    def _add_device(self) -> PushDevice:
        return PushDevice.objects.create(user=self.user, expo_token=TOKEN, platform="android")

    def test_creates_in_app_record_with_deep_link(self) -> None:
        n = self._emit()
        self.assertIsNotNone(n)
        self.assertEqual(n.event, "draft")
        self.assertEqual(n.title, "Draft saved")
        self.assertEqual(n.account_id, self.account.pk)
        self.assertEqual(n.data["deep_link"], "mailpilot://thread/t1")
        self.assertIn("client@example.com", n.body)
        self.assertIsNone(n.read_at)

    def test_duplicate_event_for_same_message_is_dropped(self) -> None:
        self._emit()
        self.assertIsNone(self._emit())
        self.assertEqual(Notification.objects.count(), 1)

    def test_disabled_event_is_not_recorded(self) -> None:
        save_preferences(self.user, {"events": {"sent": False}})
        self.assertIsNone(self._emit("sent"))
        self.assertFalse(Notification.objects.exists())

    def test_fallback_sends_external_when_no_device_and_offline(self) -> None:
        n = self._emit()
        self.telegram.assert_called_once()
        self.assertEqual(n.delivered_channels["push"], "no_device")
        self.assertEqual(n.delivered_channels["external"], "sent")
        self.assertIn("MailPilot draft saved", self.telegram.call_args.args[2])

    def test_external_send_is_retried_once_after_failure(self) -> None:
        self.telegram.side_effect = ["failed", "sent"]
        n = self._emit()
        self.assertEqual(self.telegram.call_count, 2)
        self.assertEqual(n.delivered_channels["telegram"], "sent")

    def test_fallback_skips_external_when_user_is_online(self) -> None:
        UserProfile.objects.create(user=self.user, last_seen_at=timezone.now())
        n = self._emit()
        self.telegram.assert_not_called()
        self.assertEqual(n.delivered_channels["external"], "skipped_user_active")

    def test_fallback_skips_external_when_push_delivered(self) -> None:
        self._add_device()
        self.post.return_value = _expo_response([{"status": "ok", "id": "x"}])
        n = self._emit()
        self.telegram.assert_not_called()
        self.assertEqual(n.delivered_channels["push"], "sent")
        sent = self.post.call_args.kwargs["json"][0]
        self.assertEqual(sent["to"], TOKEN)
        self.assertEqual(sent["data"]["notification_id"], n.pk)
        self.assertEqual(sent["badge"], 1)

    def test_unregistered_device_is_deactivated_and_falls_back(self) -> None:
        device = self._add_device()
        self.post.return_value = _expo_response(
            [{"status": "error", "message": "gone", "details": {"error": "DeviceNotRegistered"}}]
        )
        n = self._emit()
        device.refresh_from_db()
        self.assertFalse(device.is_active)
        self.assertEqual(n.delivered_channels["push"], "failed")
        self.telegram.assert_called_once()

    def test_always_mode_sends_external_even_with_push(self) -> None:
        save_preferences(self.user, {"external_mode": "always"})
        self._add_device()
        self.post.return_value = _expo_response([{"status": "ok", "id": "x"}])
        self._emit()
        self.telegram.assert_called_once()

    def test_off_mode_never_sends_external(self) -> None:
        save_preferences(self.user, {"external_mode": "off"})
        n = self._emit()
        self.telegram.assert_not_called()
        self.assertEqual(n.delivered_channels["external"], "disabled")

    def test_push_disabled_preference(self) -> None:
        save_preferences(self.user, {"push": False})
        self._add_device()
        n = self._emit()
        self.post.assert_not_called()
        self.assertEqual(n.delivered_channels["push"], "disabled")

    def test_quiet_hours_hold_back_everything_but_errors(self) -> None:
        save_preferences(self.user, {"quiet_hours": {"enabled": True, "start": "00:00", "end": "23:59"}})
        self._add_device()
        self.post.return_value = _expo_response([{"status": "ok", "id": "x"}])
        with mock.patch("core.notifications.delivery.in_quiet_hours", return_value=True):
            draft = self._emit("draft", "m1")
            self.assertEqual(draft.delivered_channels["push"], "quiet_hours")
            self.assertEqual(draft.delivered_channels["external"], "quiet_hours")
            self.post.assert_not_called()
            error = self._emit("error", "m2", error="SMTP down")
        self.assertEqual(error.delivered_channels["push"], "sent")

    def test_rate_limit_suppresses_then_digest_flushes_once(self) -> None:
        with override_settings(NOTIFY_EXTERNAL_RATE_LIMIT=2):
            for i in range(4):
                self._emit("draft", f"m{i}")
        statuses = list(Notification.objects.order_by("id").values_list("delivered_channels__external", flat=True))
        self.assertEqual(statuses, ["sent", "sent", "suppressed", "suppressed"])
        self.assertEqual(self.telegram.call_count, 2)

        self.assertEqual(flush_digests(), 1)
        self.assertEqual(self.telegram.call_count, 3)
        digest_text = self.telegram.call_args.args[2]
        self.assertIn("2 new notifications", digest_text)
        self.assertEqual(self.telegram.call_args.args[1], "digest")
        self.assertFalse(Notification.objects.filter(delivered_channels__external="suppressed").exists())
        self.assertEqual(flush_digests(), 0)

    def test_delivery_runs_only_once(self) -> None:
        from core.notifications.delivery import deliver

        n = self._emit()
        deliver(n.pk)
        self.telegram.assert_called_once()

    def test_in_app_disabled_records_as_read(self) -> None:
        save_preferences(self.user, {"in_app": False})
        n = self._emit()
        self.assertIsNotNone(n.read_at)

    def test_unknown_tenant_is_ignored(self) -> None:
        self.assertIsNone(notify_mail_event("not-a-user", "draft"))
        self.assertIsNone(notify_mail_event("999999", "draft"))

    def test_cleanup_removes_old_notifications(self) -> None:
        old = self._emit("draft", "old")
        self._emit("draft", "new")
        Notification.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=120))
        self.assertEqual(cleanup_old_notifications(), 1)
        self.assertEqual(Notification.objects.count(), 1)


class QuietHoursTests(TestCase):
    def _prefs(self, start: str, end: str) -> dict:
        return {"quiet_hours": {"enabled": True, "start": start, "end": end}}

    def _at(self, hh: int, mm: int = 0) -> datetime:
        return datetime(2026, 10, 13, hh, mm, tzinfo=dt_timezone.utc)

    def test_window_across_midnight(self) -> None:
        prefs = self._prefs("23:00", "07:00")
        self.assertTrue(in_quiet_hours(prefs, "UTC", self._at(23, 30)))
        self.assertTrue(in_quiet_hours(prefs, "UTC", self._at(3)))
        self.assertFalse(in_quiet_hours(prefs, "UTC", self._at(7)))
        self.assertFalse(in_quiet_hours(prefs, "UTC", self._at(12)))

    def test_uses_user_time_zone(self) -> None:
        prefs = self._prefs("23:00", "07:00")
        self.assertTrue(in_quiet_hours(prefs, "Asia/Dhaka", self._at(18)))
        self.assertFalse(in_quiet_hours(prefs, "UTC", self._at(18)))

    def test_disabled_or_invalid_zone(self) -> None:
        self.assertFalse(in_quiet_hours({"quiet_hours": {"enabled": False}}, "UTC", self._at(3)))
        self.assertTrue(in_quiet_hours(self._prefs("02:00", "04:00"), "Not/AZone", self._at(3)))
