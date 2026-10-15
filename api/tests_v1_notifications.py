from __future__ import annotations

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Notification, PushDevice, UserProfile

TOKEN = "ExponentPushToken[device-1]"


@override_settings(SECURE_SSL_REDIRECT=False)
class V1NotificationApiTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user("bell", "bell@example.com", "pw-12345678")
        self.other = User.objects.create_user("other", "other@example.com", "pw-12345678")
        self.api = self._client_for(self.user)

    def _client_for(self, user) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return client

    def _make(self, user=None, n: int = 1, event: str = "draft") -> list[Notification]:
        return [
            Notification.objects.create(user=user or self.user, event=event, title=f"N{i}", body="b")
            for i in range(n)
        ]

    def test_requires_auth(self) -> None:
        self.assertEqual(APIClient().get("/api/v1/notifications").status_code, 401)

    def test_list_paginates_newest_first_and_only_own(self) -> None:
        self._make(n=5)
        self._make(user=self.other, n=2)
        res = self.api.get("/api/v1/notifications?limit=3").json()
        self.assertEqual([i["title"] for i in res["items"]], ["N4", "N3", "N2"])
        self.assertEqual(res["unread_count"], 5)
        self.assertIsNotNone(res["next_cursor"])
        page2 = self.api.get(f"/api/v1/notifications?limit=3&cursor={res['next_cursor']}").json()
        self.assertEqual([i["title"] for i in page2["items"]], ["N1", "N0"])
        self.assertIsNone(page2["next_cursor"])

    def test_unread_filter_and_count_marks_user_active(self) -> None:
        first, second = self._make(n=2)
        self.api.post(f"/api/v1/notifications/{first.pk}/read")
        res = self.api.get("/api/v1/notifications?unread=1").json()
        self.assertEqual([i["id"] for i in res["items"]], [second.pk])

        count = self.api.get("/api/v1/notifications/unread-count").json()
        self.assertEqual(count["unread_count"], 1)
        self.assertEqual(count["latest"]["id"], second.pk)
        self.assertIsNotNone(UserProfile.objects.get(user=self.user).last_seen_at)

    def test_read_rejects_other_users_notification(self) -> None:
        (theirs,) = self._make(user=self.other)
        self.assertEqual(self.api.post(f"/api/v1/notifications/{theirs.pk}/read").status_code, 404)
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)

    def test_read_all(self) -> None:
        self._make(n=3)
        self._make(user=self.other)
        self.assertEqual(self.api.post("/api/v1/notifications/read-all").json()["updated"], 3)
        self.assertEqual(Notification.objects.filter(read_at__isnull=True).count(), 1)

    def test_preferences_round_trip_and_validation(self) -> None:
        prefs = self.api.get("/api/v1/notifications/preferences").json()["preferences"]
        self.assertEqual(prefs["external_mode"], "fallback")

        res = self.api.put(
            "/api/v1/notifications/preferences",
            {
                "external_mode": "always",
                "events": {"sent": False},
                "quiet_hours": {"enabled": True, "start": "22:30", "end": "bogus"},
            },
            format="json",
        ).json()["preferences"]
        self.assertEqual(res["external_mode"], "always")
        self.assertFalse(res["events"]["sent"])
        self.assertTrue(res["events"]["draft"])
        self.assertEqual(res["quiet_hours"], {"enabled": True, "start": "22:30", "end": "07:00"})

        res = self.api.patch(
            "/api/v1/notifications/preferences", {"external_mode": "nonsense"}, format="json"
        ).json()["preferences"]
        self.assertEqual(res["external_mode"], "always")

    def test_device_register_validates_and_reassigns(self) -> None:
        bad = self.api.post("/api/v1/devices/register", {"expo_token": "nope"}, format="json")
        self.assertEqual(bad.status_code, 400)

        res = self.api.post(
            "/api/v1/devices/register", {"expo_token": TOKEN, "platform": "android"}, format="json"
        ).json()
        self.assertTrue(res["created"])

        again = self._client_for(self.other).post(
            "/api/v1/devices/register", {"expo_token": TOKEN, "platform": "android"}, format="json"
        ).json()
        self.assertFalse(again["created"])
        device = PushDevice.objects.get(expo_token=TOKEN)
        self.assertEqual(device.user, self.other)
        self.assertTrue(device.is_active)

    def test_device_unregister_only_affects_own_token(self) -> None:
        PushDevice.objects.create(user=self.other, expo_token=TOKEN)
        self.assertEqual(
            self.api.post("/api/v1/devices/unregister", {"expo_token": TOKEN}, format="json").json()["updated"], 0
        )
        self._client_for(self.other).post("/api/v1/devices/unregister", {"expo_token": TOKEN}, format="json")
        self.assertFalse(PushDevice.objects.get(expo_token=TOKEN).is_active)

    def test_web_session_requires_csrf_for_writes(self) -> None:
        self._make(n=1)
        web = Client(enforce_csrf_checks=True)
        web.force_login(self.user)
        self.assertEqual(web.get("/api/v1/notifications/unread-count").status_code, 200)
        self.assertEqual(web.post("/api/v1/notifications/read-all").status_code, 403)

        web.get("/settings")
        token = web.cookies["csrftoken"].value
        res = web.post("/api/v1/notifications/read-all", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 200)
