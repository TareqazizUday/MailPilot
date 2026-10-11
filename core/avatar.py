"""Profile photo validation and storage helpers (web profile page + JWT API)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile
    from django.http import HttpRequest

    from core.models import UserProfile

AVATAR_MAX_BYTES = 2 * 1024 * 1024
_ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
_ALLOWED_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def validate_avatar(upload: UploadedFile) -> str:
    """Return an error message, or an empty string when the upload is a usable image."""
    name = (getattr(upload, "name", "") or "").lower()
    if not name.endswith(_ALLOWED_EXT):
        return "Avatar must be an image file (PNG/JPG/WEBP/GIF)."
    if getattr(upload, "size", 0) and upload.size > AVATAR_MAX_BYTES:
        return "Avatar is too large. Max 2 MB."
    try:
        from PIL import Image

        upload.seek(0)
        with Image.open(upload) as img:
            fmt = (img.format or "").upper()
            img.verify()
        if fmt not in _ALLOWED_FORMATS:
            return "Avatar must be an image file (PNG/JPG/WEBP/GIF)."
    except Exception:
        return "That file is not a valid image."
    finally:
        try:
            upload.seek(0)
        except Exception:
            pass
    return ""


def _delete_file(prof: UserProfile) -> None:
    try:
        if prof.avatar and prof.avatar.name and prof.avatar.storage.exists(prof.avatar.name):
            prof.avatar.delete(save=False)
    except Exception:
        pass


def save_avatar(prof: UserProfile, upload: UploadedFile) -> None:
    _delete_file(prof)
    prof.avatar = upload
    prof.save(update_fields=["avatar", "updated_at"])


def remove_avatar(prof: UserProfile) -> None:
    _delete_file(prof)
    prof.avatar = None
    prof.save(update_fields=["avatar", "updated_at"])


def avatar_url(prof: UserProfile, request: HttpRequest | None = None) -> str:
    """URL for the stored avatar, or empty when missing (avoids broken /media links)."""
    try:
        if prof.avatar and prof.avatar.name and prof.avatar.storage.exists(prof.avatar.name):
            url = prof.avatar.url
            return request.build_absolute_uri(url) if request is not None else url
    except Exception:
        return ""
    return ""
