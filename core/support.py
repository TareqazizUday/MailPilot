"""Support ticket helpers: validation, serialization, unread counts."""
from __future__ import annotations

import os
from typing import Any

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet
from django.utils import timezone

from core.models import SupportAttachment, SupportMessage, SupportTicket

ALLOWED_IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES_PER_MESSAGE = 2
MAX_BODY_LENGTH = 8000
MAX_SUBJECT_LENGTH = 200

OPEN_TICKET_STATUSES = frozenset(
    {
        SupportTicket.STATUS_OPEN,
        SupportTicket.STATUS_WAITING_ADMIN,
        SupportTicket.STATUS_WAITING_USER,
    }
)


def validate_support_image(upload: UploadedFile) -> None:
    name = (getattr(upload, "name", "") or "").lower()
    ext = os.path.splitext(name)[1]
    if ext not in ALLOWED_IMAGE_EXT:
        raise ValidationError("Only PNG, JPG, WEBP, and GIF images are allowed.")
    mime = str(getattr(upload, "content_type", "") or "").strip().lower()
    if mime and not mime.startswith("image/"):
        raise ValidationError("Invalid image file type.")
    size = int(getattr(upload, "size", 0) or 0)
    if size > MAX_IMAGE_BYTES:
        raise ValidationError("Image is too large (max 5 MB).")


def collect_support_images(request, *, field: str = "images") -> list[UploadedFile]:
    files = request.FILES.getlist(field) or request.FILES.getlist("files") or []
    if len(files) > MAX_IMAGES_PER_MESSAGE:
        raise ValidationError(f"Maximum {MAX_IMAGES_PER_MESSAGE} images per message.")
    for f in files:
        validate_support_image(f)
    return list(files)


def normalize_body(raw: str) -> str:
    return (raw or "").strip()[:MAX_BODY_LENGTH]


def message_has_content(body: str, images: list[UploadedFile]) -> bool:
    return bool(body) or bool(images)


def support_unread_count_for_user(user) -> int:
    if not user or not getattr(user, "is_authenticated", False):
        return 0
    return SupportTicket.objects.filter(user=user, unread_by_user=True).count()


def support_open_count_for_staff() -> int:
    return SupportTicket.objects.filter(
        unread_by_staff=True,
        status__in=OPEN_TICKET_STATUSES,
    ).count()


def staff_ticket_queryset() -> QuerySet[SupportTicket]:
    return SupportTicket.objects.select_related("user").order_by("-last_message_at", "-id")


def user_ticket_queryset(user) -> QuerySet[SupportTicket]:
    return SupportTicket.objects.filter(user=user).select_related("user")


def ticket_for_user(user, ticket_id: int) -> SupportTicket | None:
    return user_ticket_queryset(user).filter(pk=ticket_id).first()


def ticket_for_staff(ticket_id: int) -> SupportTicket | None:
    return SupportTicket.objects.select_related("user").filter(pk=ticket_id).first()


def mark_ticket_read_by_user(ticket: SupportTicket) -> None:
    if ticket.unread_by_user:
        ticket.unread_by_user = False
        ticket.save(update_fields=["unread_by_user", "updated_at"])


def mark_ticket_read_by_staff(ticket: SupportTicket) -> None:
    if ticket.unread_by_staff:
        ticket.unread_by_staff = False
        ticket.save(update_fields=["unread_by_staff", "updated_at"])


def attachment_to_dict(att: SupportAttachment, *, request) -> dict[str, Any]:
    return {
        "id": att.pk,
        "original_name": att.original_name,
        "content_type": att.content_type,
        "size_bytes": att.size_bytes,
        "view_url": f"/api/support/attachments/{att.pk}/view",
        "is_image": (att.content_type or "").startswith("image/"),
    }


def message_to_dict(msg: SupportMessage, *, request, for_staff: bool = False) -> dict[str, Any]:
    attachments = [attachment_to_dict(a, request=request) for a in msg.attachments.all()]
    sender = msg.sender
    if msg.is_staff_reply:
        label = "Support"
    elif for_staff:
        label = sender.get_full_name() or sender.username or sender.email or "User"
    else:
        label = sender.get_full_name() or sender.username or "You"
    return {
        "id": msg.pk,
        "body": msg.body,
        "is_staff_reply": msg.is_staff_reply,
        "sender_label": label,
        "created_at": msg.created_at.isoformat(),
        "attachments": attachments,
    }


def ticket_to_dict(
    ticket: SupportTicket,
    *,
    request,
    include_messages: bool = False,
    for_staff: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": ticket.pk,
        "subject": ticket.subject,
        "category": ticket.category,
        "category_label": ticket.get_category_display(),
        "status": ticket.status,
        "status_label": ticket.get_status_display(),
        "unread_by_user": ticket.unread_by_user,
        "unread_by_staff": ticket.unread_by_staff,
        "last_message_at": ticket.last_message_at.isoformat() if ticket.last_message_at else None,
        "created_at": ticket.created_at.isoformat(),
        "detail_url": f"/support/{ticket.pk}",
    }
    if for_staff:
        user = ticket.user
        data["user_label"] = user.get_full_name() or user.username or "User"
        data["user_email"] = user.email or ""
        data["admin_detail_url"] = f"/admin/support/inbox/{ticket.pk}/"
    if include_messages:
        msgs = ticket.messages.prefetch_related("attachments").select_related("sender")
        data["messages"] = [message_to_dict(m, request=request) for m in msgs]
    return data


def save_support_images(message: SupportMessage, images: list[UploadedFile]) -> list[SupportAttachment]:
    saved: list[SupportAttachment] = []
    for upload in images:
        att = SupportAttachment(
            message=message,
            original_name=(upload.name or "image")[:255],
            content_type=str(getattr(upload, "content_type", "") or "")[:128],
            size_bytes=int(getattr(upload, "size", 0) or 0),
        )
        att.file = upload
        att.save()
        saved.append(att)
    return saved


def create_support_message(
    *,
    ticket: SupportTicket,
    sender,
    body: str,
    images: list[UploadedFile],
    is_staff_reply: bool,
) -> SupportMessage:
    body = normalize_body(body)
    if not message_has_content(body, images):
        raise ValidationError("Enter a message or attach an image.")

    msg = SupportMessage.objects.create(
        ticket=ticket,
        sender=sender,
        body=body,
        is_staff_reply=is_staff_reply,
    )
    save_support_images(msg, images)

    ticket.last_message_at = timezone.now()
    if is_staff_reply:
        ticket.status = SupportTicket.STATUS_WAITING_USER
        ticket.unread_by_user = True
        ticket.unread_by_staff = False
    else:
        if ticket.status in (SupportTicket.STATUS_RESOLVED, SupportTicket.STATUS_CLOSED):
            ticket.status = SupportTicket.STATUS_OPEN
        else:
            ticket.status = SupportTicket.STATUS_WAITING_ADMIN
        ticket.unread_by_staff = True
        ticket.unread_by_user = False
    ticket.save(
        update_fields=[
            "status",
            "unread_by_user",
            "unread_by_staff",
            "last_message_at",
            "updated_at",
        ]
    )
    return msg
