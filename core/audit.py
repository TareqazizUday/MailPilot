from __future__ import annotations

from django.http import HttpRequest

from core.models import AuditLog


def log_audit(request: HttpRequest, action: str, detail: str = "") -> None:
    uid = request.user.id if request.user.is_authenticated else None
    ip = request.META.get("REMOTE_ADDR")
    try:
        AuditLog.objects.create(user_id=uid, action=action, detail=(detail or "")[:512], ip_address=ip)
    except Exception:
        pass
