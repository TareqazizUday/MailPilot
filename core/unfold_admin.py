from __future__ import annotations

from core.admin_dashboard import build_chart_payload, build_dashboard_stats


def dashboard_callback(request, context):
    charts = build_chart_payload()
    context.update(
        {
            "mp_stats": build_dashboard_stats(),
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
