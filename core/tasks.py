"""Background mail polling tasks (Celery)."""
from __future__ import annotations

import logging

from celery import shared_task
from django.contrib.auth.models import User

from core import runtime
from core.models import UserMailSettings

log = logging.getLogger("mailpilot.tasks")


@shared_task(ignore_result=True)
def poll_user_mail(user_id: int) -> None:
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return
    try:
        runtime.trigger_poll_fn(user=user)
    except Exception as e:
        log.warning("poll_user_mail failed user=%s: %s", user_id, e)


@shared_task(ignore_result=True)
def poll_all_users_mail() -> None:
    """Scheduled beat task: poll every user with saved mail settings."""
    ids = list(UserMailSettings.objects.values_list("user_id", flat=True).distinct())
    if not ids:
        try:
            runtime.trigger_poll_fn(user=None)
        except Exception as e:
            log.warning("poll legacy failed: %s", e)
        return
    for uid in ids:
        poll_user_mail.delay(int(uid))
