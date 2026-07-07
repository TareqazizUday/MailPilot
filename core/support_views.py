"""Support ticket pages and JSON API (text + image chat)."""
from __future__ import annotations

import logging
import mimetypes

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from django_ratelimit.decorators import ratelimit

from core import runtime
from core.models import SupportAttachment, SupportMessage, SupportTicket
from core.support import (
    MAX_SUBJECT_LENGTH,
    collect_support_images,
    create_support_message,
    mark_ticket_read_by_staff,
    mark_ticket_read_by_user,
    message_to_dict,
    normalize_body,
    staff_ticket_queryset,
    support_open_count_for_staff,
    support_unread_count_for_user,
    ticket_for_staff,
    ticket_for_user,
    ticket_to_dict,
    user_ticket_queryset,
)
from core.support_mail import notify_staff_new_ticket
from core.views import _mailbox_connected_for_ui, _user_settings_dict

logger = logging.getLogger("mailpilot.support.views")


def _staff_check(user) -> bool:
    return bool(user and user.is_authenticated and user.is_staff)


def _page_connected(request):
    from core.user_settings import migrate_legacy_file_config_if_needed

    migrate_legacy_file_config_if_needed(request.user)
    effective = runtime.get_effective_settings(request.user)
    cfg = _user_settings_dict(request)
    return _mailbox_connected_for_ui(effective, cfg)


def _json_error(message: str, *, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _is_support_url_name(url_name: str | None) -> bool:
    return url_name in {
        "support",
        "support_new",
        "support_detail",
        "support_admin_inbox",
        "support_admin_detail",
    }


def _staff_page_context(request, **extra):
    return {
        "connected": _page_connected(request),
        "staff_unread_count": support_open_count_for_staff(),
        **extra,
    }


@user_passes_test(_staff_check, login_url="/admin/login/")
@require_GET
def support_admin_inbox_page(request):
    return redirect(reverse("admin:support_inbox"))


@user_passes_test(_staff_check, login_url="/admin/login/")
@require_GET
def support_admin_detail_page(request, ticket_id: int):
    return redirect(reverse("admin:support_inbox_detail", args=[ticket_id]))


@login_required(login_url="/login")
@require_GET
def support_list_page(request):
    tickets = user_ticket_queryset(request.user)[:100]
    return render(
        request,
        "support_list.html",
        {
            "connected": _page_connected(request),
            "tickets": tickets,
            "unread_count": support_unread_count_for_user(request.user),
        },
    )


@login_required(login_url="/login")
@require_GET
def support_new_page(request):
    category = (request.GET.get("category") or SupportTicket.CATEGORY_OTHER).strip().lower()
    if category not in dict(SupportTicket.CATEGORY_CHOICES):
        category = SupportTicket.CATEGORY_OTHER
    return render(
        request,
        "support_new.html",
        {
            "connected": _page_connected(request),
            "default_category": category,
            "categories": SupportTicket.CATEGORY_CHOICES,
        },
    )


@login_required(login_url="/login")
@require_GET
def support_detail_page(request, ticket_id: int):
    ticket = ticket_for_user(request.user, ticket_id)
    if ticket is None:
        raise Http404
    mark_ticket_read_by_user(ticket)
    return render(
        request,
        "support_detail.html",
        {
            "connected": _page_connected(request),
            "ticket": ticket,
            "ticket_id": ticket.pk,
        },
    )


@login_required(login_url="/login")
@require_GET
def api_support_tickets_list(request):
    tickets = user_ticket_queryset(request.user)[:100]
    return JsonResponse(
        {
            "ok": True,
            "tickets": [ticket_to_dict(t, request=request) for t in tickets],
            "unread_count": support_unread_count_for_user(request.user),
        }
    )


@login_required(login_url="/login")
@ratelimit(key="user", rate="20/h", method="POST", block=True)
@require_http_methods(["POST"])
def api_support_tickets_create(request):
    subject = normalize_body(request.POST.get("subject") or "")[:MAX_SUBJECT_LENGTH]
    category = (request.POST.get("category") or SupportTicket.CATEGORY_OTHER).strip().lower()
    body = normalize_body(request.POST.get("body") or "")
    if category not in dict(SupportTicket.CATEGORY_CHOICES):
        category = SupportTicket.CATEGORY_OTHER
    if not subject:
        return _json_error("Subject is required.")
    try:
        images = collect_support_images(request)
    except ValidationError as e:
        return _json_error(str(e))

    try:
        with transaction.atomic():
            ticket = SupportTicket.objects.create(
                user=request.user,
                subject=subject,
                category=category,
                status=SupportTicket.STATUS_OPEN,
                unread_by_staff=True,
                unread_by_user=False,
            )
            msg = create_support_message(
                ticket=ticket,
                sender=request.user,
                body=body,
                images=images,
                is_staff_reply=False,
            )
    except ValidationError as e:
        return _json_error(str(e))

    notify_staff_new_ticket(ticket, msg)
    return JsonResponse(
        {
            "ok": True,
            "ticket": ticket_to_dict(ticket, request=request, include_messages=True),
            "redirect": reverse("support_detail", args=[ticket.pk]),
        }
    )


@login_required(login_url="/login")
@require_GET
def api_support_ticket_messages(request, ticket_id: int):
    ticket = ticket_for_user(request.user, ticket_id)
    if ticket is None:
        return _json_error("Ticket not found.", status=404)
    mark_ticket_read_by_user(ticket)
    msgs = ticket.messages.prefetch_related("attachments").select_related("sender")
    return JsonResponse(
        {
            "ok": True,
            "ticket": ticket_to_dict(ticket, request=request),
            "messages": [message_to_dict(m, request=request) for m in msgs],
        }
    )


@login_required(login_url="/login")
@ratelimit(key="user", rate="60/h", method="POST", block=True)
@require_http_methods(["POST"])
def api_support_ticket_reply(request, ticket_id: int):
    ticket = ticket_for_user(request.user, ticket_id)
    if ticket is None:
        return _json_error("Ticket not found.", status=404)
    if ticket.status == SupportTicket.STATUS_CLOSED:
        return _json_error("This ticket is closed. Open a new ticket if you need more help.")

    body = normalize_body(request.POST.get("body") or "")
    try:
        images = collect_support_images(request)
    except ValidationError as e:
        return _json_error(str(e))

    try:
        with transaction.atomic():
            msg = create_support_message(
                ticket=ticket,
                sender=request.user,
                body=body,
                images=images,
                is_staff_reply=False,
            )
    except ValidationError as e:
        return _json_error(str(e))

    notify_staff_new_ticket(ticket, msg)
    return JsonResponse({"ok": True, "message": message_to_dict(msg, request=request)})


@login_required(login_url="/login")
@require_GET
def api_support_attachment_view(request, attachment_id: int):
    att = (
        SupportAttachment.objects.select_related("message__ticket__user")
        .filter(pk=attachment_id)
        .first()
    )
    if att is None:
        raise Http404
    ticket = att.message.ticket
    if ticket.user_id != request.user.id and not request.user.is_staff:
        raise Http404
    if not att.file or not att.file.name:
        raise Http404
    try:
        if not att.file.storage.exists(att.file.name):
            raise Http404
    except Exception:
        raise Http404
    content_type = att.content_type or mimetypes.guess_type(att.original_name)[0] or "application/octet-stream"
    return FileResponse(att.file.open("rb"), content_type=content_type, filename=att.original_name)


@user_passes_test(_staff_check, login_url="/admin/login/")
@require_GET
def api_support_admin_tickets_list(request):
    tickets = staff_ticket_queryset()[:200]
    return JsonResponse(
        {
            "ok": True,
            "tickets": [ticket_to_dict(t, request=request, for_staff=True) for t in tickets],
            "unread_count": support_open_count_for_staff(),
        }
    )


@user_passes_test(_staff_check, login_url="/admin/login/")
@require_GET
def api_support_admin_ticket_messages(request, ticket_id: int):
    ticket = ticket_for_staff(ticket_id)
    if ticket is None:
        return _json_error("Ticket not found.", status=404)
    mark_ticket_read_by_staff(ticket)
    msgs = ticket.messages.prefetch_related("attachments").select_related("sender")
    return JsonResponse(
        {
            "ok": True,
            "ticket": ticket_to_dict(ticket, request=request, for_staff=True),
            "messages": [message_to_dict(m, request=request, for_staff=True) for m in msgs],
        }
    )


@user_passes_test(_staff_check, login_url="/admin/login/")
@ratelimit(key="user", rate="120/h", method="POST", block=True)
@require_http_methods(["POST"])
def api_support_admin_reply(request, ticket_id: int):
    ticket = ticket_for_staff(ticket_id)
    if ticket is None:
        return _json_error("Ticket not found.", status=404)
    if ticket.status == SupportTicket.STATUS_CLOSED:
        status_action = (request.POST.get("status") or "").strip().lower()
        if status_action != "closed":
            return _json_error("This ticket is closed. Chat is read-only.")

    body = normalize_body(request.POST.get("body") or "")
    try:
        images = collect_support_images(request)
    except ValidationError as e:
        return _json_error(str(e))

    status_action = (request.POST.get("status") or "").strip().lower()
    has_content = bool(body) or bool(images)

    if status_action == "closed" and not has_content:
        ticket.status = SupportTicket.STATUS_CLOSED
        ticket.unread_by_user = False
        ticket.unread_by_staff = False
        ticket.save(update_fields=["status", "unread_by_user", "unread_by_staff", "updated_at"])
        return JsonResponse({"ok": True, "ticket": ticket_to_dict(ticket, request=request, for_staff=True)})

    try:
        with transaction.atomic():
            msg = None
            if has_content:
                msg = create_support_message(
                    ticket=ticket,
                    sender=request.user,
                    body=body,
                    images=images,
                    is_staff_reply=True,
                )
            elif status_action not in {"resolved", "closed"}:
                return _json_error("Enter a message or attach an image.")

            if status_action == "resolved":
                ticket.status = SupportTicket.STATUS_RESOLVED
                ticket.unread_by_user = True
                ticket.save(update_fields=["status", "unread_by_user", "updated_at"])
            elif status_action == "closed":
                ticket.status = SupportTicket.STATUS_CLOSED
                ticket.unread_by_user = False
                ticket.unread_by_staff = False
                ticket.save(update_fields=["status", "unread_by_user", "unread_by_staff", "updated_at"])
    except ValidationError as e:
        return _json_error(str(e))

    if msg is not None:
        mark_ticket_read_by_staff(ticket)
        ticket.refresh_from_db()
        return JsonResponse(
            {
                "ok": True,
                "message": message_to_dict(msg, request=request, for_staff=True),
                "ticket": ticket_to_dict(ticket, request=request, for_staff=True),
            }
        )

    mark_ticket_read_by_staff(ticket)
    ticket.refresh_from_db()
    return JsonResponse({"ok": True, "ticket": ticket_to_dict(ticket, request=request, for_staff=True)})
