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
