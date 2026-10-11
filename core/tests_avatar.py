from __future__ import annotations

import io
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import UserProfile


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (91, 91, 240)).save(buf, format="PNG")
    return buf.getvalue()


class AvatarUploadTests(TestCase):
    def setUp(self) -> None:
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media, SECURE_SSL_REDIRECT=False)
        self.override.enable()
        self.user = User.objects.create_user(username="ava", password="pass12345", email="ava@example.com")

    def tearDown(self) -> None:
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def _api(self) -> APIClient:
        client = APIClient()
        token = RefreshToken.for_user(self.user).access_token
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def test_web_profile_upload_and_remove(self) -> None:
        self.client.force_login(self.user)
        upload = SimpleUploadedFile("me.png", _png_bytes(), content_type="image/png")
        self.client.post("/profile", {"avatar": upload, "email": "ava@example.com"})
        prof = UserProfile.objects.get(user=self.user)
        self.assertTrue(prof.avatar.name.startswith("avatars/"))

        self.client.post("/profile", {"remove_avatar": "1", "email": "ava@example.com"})
        prof.refresh_from_db()
        self.assertFalse(prof.avatar)

    def test_web_profile_rejects_fake_image(self) -> None:
        self.client.force_login(self.user)
        fake = SimpleUploadedFile("evil.png", b"not an image", content_type="image/png")
        self.client.post("/profile", {"avatar": fake, "email": "ava@example.com"})
        prof = UserProfile.objects.get(user=self.user)
        self.assertFalse(prof.avatar)

    def test_api_upload_and_delete(self) -> None:
        client = self._api()
        upload = SimpleUploadedFile("me.png", _png_bytes(), content_type="image/png")
        res = client.post("/api/v1/me/avatar", {"avatar": upload}, format="multipart")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()["user"]["avatar_url"])

        res = client.delete("/api/v1/me/avatar")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.json()["user"]["avatar_url"])

    def test_api_rejects_oversize(self) -> None:
        client = self._api()
        big = SimpleUploadedFile("big.png", b"0" * (2 * 1024 * 1024 + 1), content_type="image/png")
        res = client.post("/api/v1/me/avatar", {"avatar": big}, format="multipart")
        self.assertEqual(res.status_code, 400)
