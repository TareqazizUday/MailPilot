from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from core.models import ContactSubmission

logger = logging.getLogger("mailpilot.contact")


def team_inbox() -> str:
    return (getattr(settings, "CONTACT_TEAM_EMAIL", None) or "team@timerni.co.uk").strip()


def send_contact_submission_emails(submission: ContactSubmission) -> tuple[bool, bool]:
    """Notify the team and send an auto-reply to the submitter."""
    ctx = {
        "name": submission.name,
        "email": submission.email,
        "phone": submission.phone,
        "message": submission.message,
        "submission_id": submission.pk,
    }
    team_ok = _send_team_notification(submission, ctx)
    user_ok = _send_user_confirmation(submission, ctx)
    return team_ok, user_ok


def _send_team_notification(submission: ContactSubmission, ctx: dict) -> bool:
    to_addr = team_inbox()
    subject = f"[MailPilot] Contact from {submission.name}"
    text_body = render_to_string("emails/contact_team.txt", ctx).strip() + "\n"
    html_body = render_to_string("emails/contact_team.html", ctx)
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_addr],
        reply_to=[submission.email],
    )
    msg.attach_alternative(html_body, "text/html")
    try:
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("contact team email failed (submission id=%s)", submission.pk)
        return False


def _send_user_confirmation(submission: ContactSubmission, ctx: dict) -> bool:
    subject = "We received your message | MailPilot"
    text_body = render_to_string("emails/contact_user_confirm.txt", ctx).strip() + "\n"
    html_body = render_to_string("emails/contact_user_confirm.html", ctx)
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[submission.email],
    )
    msg.attach_alternative(html_body, "text/html")
    try:
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("contact user confirmation failed (submission id=%s)", submission.pk)
        return False
