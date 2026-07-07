from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from core.contact_mail import team_inbox
from core.models import SupportMessage, SupportTicket

logger = logging.getLogger("mailpilot.support")


def _ticket_url(ticket_id: int) -> str:
    base = (getattr(settings, "SITE_URL", "") or "").strip().rstrip("/")
    if not base:
        return f"/support/{ticket_id}"
    return f"{base}/support/{ticket_id}"


def _admin_ticket_url(ticket_id: int) -> str:
    base = (getattr(settings, "SITE_URL", "") or "").strip().rstrip("/")
    if not base:
        return f"/admin/support/inbox/{ticket_id}/"
    return f"{base}/admin/support/inbox/{ticket_id}/"


def notify_staff_new_ticket(ticket: SupportTicket, message: SupportMessage) -> bool:
    to_addr = team_inbox()
    if not to_addr:
        return False
    user = ticket.user
    subject = f"[MailPilot Support] New ticket #{ticket.pk}: {ticket.subject}"
    body = (
        f"New support ticket from {user.get_full_name() or user.username} ({user.email})\n"
        f"Category: {ticket.get_category_display()}\n"
        f"Subject: {ticket.subject}\n\n"
        f"Message:\n{message.body or '(image attachment)'}\n\n"
        f"Admin: {_admin_ticket_url(ticket.pk)}\n"
        f"User thread: {_ticket_url(ticket.pk)}\n"
    )
    try:
        EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_addr],
            reply_to=[user.email] if user.email else None,
        ).send(fail_silently=False)
        return True
    except Exception:
        logger.exception("support staff notification failed ticket=%s", ticket.pk)
        return False


def notify_user_staff_reply(ticket: SupportTicket, message: SupportMessage) -> bool:
    user = ticket.user
    email = (user.email or "").strip()
    if not email:
        return False
    subject = f"MailPilot Support replied · Ticket #{ticket.pk}"
    body = (
        f"Hi {user.get_full_name() or user.username},\n\n"
        f"Our team replied to your support ticket \"{ticket.subject}\":\n\n"
        f"{message.body or '(see attachment in MailPilot)'}\n\n"
        f"View and reply: {_ticket_url(ticket.pk)}\n"
    )
    try:
        EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        ).send(fail_silently=False)
        return True
    except Exception:
        logger.exception("support user notification failed ticket=%s", ticket.pk)
        return False
