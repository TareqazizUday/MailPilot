from __future__ import annotations

from django.contrib.auth.models import User
from django.db.models import Sum
from django.utils import timezone

from core.billing import current_period_key
from core.models import ContactSubmission, MailAccount, UsageCounter, UsageEvent, UserSubscription


def dashboard_callback(request, context):
    period = current_period_key()
    tokens_agg = UsageCounter.objects.filter(period_key=period).aggregate(total=Sum("tokens_used"))
    context.update(
        {
            "mp_stats": {
                "users": User.objects.count(),
                "subscriptions": UserSubscription.objects.count(),
                "pro_plans": UserSubscription.objects.filter(plan_code=UserSubscription.PLAN_PRO).count(),
                "active_mailboxes": MailAccount.objects.filter(is_enabled=True).count(),
                "tokens_this_month": int(tokens_agg.get("total") or 0),
                "auto_sends_today": UsageEvent.objects.filter(
                    date=timezone.localdate(),
                    status=UsageEvent.STATUS_COMMITTED,
                ).count(),
                "open_contacts": ContactSubmission.objects.filter(notified_team=False).count(),
            },
            "mp_period": period,
        }
    )
    return context


def environment_callback(request):
    return ["MailPilot", "primary"]


def contact_badge_callback(request):
    count = ContactSubmission.objects.filter(notified_team=False).count()
    return count if count else ""


def payment_gateway_badge(request):
    from core.payment_gateway import stripe_checkout_ready

    return "" if stripe_checkout_ready() else "!"
