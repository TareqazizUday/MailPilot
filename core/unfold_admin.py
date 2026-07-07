from __future__ import annotations

from core.admin_dashboard import build_chart_payload, build_dashboard_stats, build_support_dashboard_slice, _user_label
from core.usage_analytics import build_usage_economics
from core.billing import current_period_key


def dashboard_callback(request, context):
    period = current_period_key()
    usage_economics = build_usage_economics(period, user_label_fn=_user_label)
    charts = build_chart_payload(usage_economics=usage_economics)
    context.update(
        {
            "mp_stats": build_dashboard_stats(usage_economics=usage_economics),
            "mp_support": build_support_dashboard_slice(),
            "mp_charts": charts,
            "mp_period": charts["period"],
        }
    )
    return context


def environment_callback(request):
    return ["MailPilot", "primary"]


def contact_badge_callback(request):
    from core.models import ContactSubmission

    count = ContactSubmission.objects.filter(notified_team=False).count()
    return count if count else ""


def support_inbox_badge_callback(request):
    try:
        from core.support import support_open_count_for_staff

        count = support_open_count_for_staff()
        return count if count else ""
    except Exception:
        return ""


def support_tickets_badge_callback(request):
    """Total support tickets (1 ticket → badge 1, 2 tickets → badge 2, …)."""
    try:
        from core.models import SupportTicket

        count = SupportTicket.objects.count()
        return count if count else ""
    except Exception:
        return ""
