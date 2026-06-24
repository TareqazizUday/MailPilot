from __future__ import annotations

from django.contrib.auth.views import LoginView
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from unfold.sites import UnfoldAdminSite

try:
    from django.contrib.auth.decorators import login_not_required
except ImportError:  # pragma: no cover
    from django.contrib.admin.sites import login_not_required


class MailPilotAdminSite(UnfoldAdminSite):
    site_header = "MailPilot"
    site_title = "MailPilot Admin"
    index_title = "Operations dashboard"
    enable_nav_sidebar = True

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "billing/gateways/",
                self.admin_view(self.billing_gateways_view),
                name="billing_gateways",
            ),
        ]
        return custom + urls

    def billing_gateways_view(self, request):
        from core.billing_deploy import billing_deploy_checks
        from core.payment_gateway import (
            PAYMENT_PAYPAL,
            PAYMENT_STRIPE,
            available_payment_providers,
            billing_use_local_checkout,
            get_paypal_credentials,
            get_stripe_credentials,
            paypal_checkout_ready,
            paypal_environment_label,
            paypal_resolved_environment,
            provider_label,
            stripe_checkout_block_reason,
            stripe_checkout_ready,
            stripe_environment_label,
            stripe_resolved_environment,
        )

        stripe_env = stripe_resolved_environment()
        paypal_env = paypal_resolved_environment()
        stripe_creds = get_stripe_credentials()
        paypal_creds = get_paypal_credentials()
        gateway_rows = []
        for code in (PAYMENT_STRIPE, PAYMENT_PAYPAL):
            if code == PAYMENT_STRIPE:
                ready = stripe_checkout_ready()
                block = stripe_checkout_block_reason() if not ready else ""
                gateway_rows.append(
                    {
                        "code": code,
                        "label": provider_label(code),
                        "environment": stripe_environment_label(),
                        "configured": bool(stripe_creds and stripe_creds.secret_key),
                        "checkout_ready": ready,
                        "block_reason": block,
                        "source": (stripe_creds.source if stripe_creds else "") or "—",
                    }
                )
            else:
                ready = paypal_checkout_ready()
                gateway_rows.append(
                    {
                        "code": code,
                        "label": provider_label(code),
                        "environment": paypal_environment_label(),
                        "configured": bool(paypal_creds and paypal_creds.client_secret),
                        "checkout_ready": ready,
                        "block_reason": "",
                        "source": (paypal_creds.source if paypal_creds else "") or "—",
                    }
                )

        context = {
            **self.each_context(request),
            "title": "Payment gateways",
            "subtitle": "Credentials are read from server .env only.",
            "gateway_rows": gateway_rows,
            "active_providers": available_payment_providers(),
            "local_checkout": billing_use_local_checkout(),
            "checks": billing_deploy_checks(),
        }
        return TemplateResponse(request, "admin/billing_gateways.html", context)

    @method_decorator(never_cache)
    @login_not_required
    def login(self, request, extra_context=None):
        if request.method == "GET" and self.has_permission(request):
            return HttpResponseRedirect(reverse("admin:index", current_app=self.name))

        from django.contrib.admin.forms import AdminAuthenticationForm
        from django.contrib.auth.views import REDIRECT_FIELD_NAME

        index_url = reverse("admin:index", current_app=self.name)
        context = {
            **self.each_context(request),
            "title": "Log in",
            "subtitle": None,
            "app_path": request.get_full_path(),
            "username": request.user.get_username(),
            "admin_index_url": index_url,
        }
        _raw_next = (request.GET.get(REDIRECT_FIELD_NAME) or request.POST.get(REDIRECT_FIELD_NAME) or "").strip()
        if not _raw_next or "/admin/login" in _raw_next.rstrip("/"):
            context[REDIRECT_FIELD_NAME] = index_url
        elif REDIRECT_FIELD_NAME not in context:
            context[REDIRECT_FIELD_NAME] = _raw_next
        context.update(extra_context or {})

        defaults = {
            "extra_context": context,
            "authentication_form": self.login_form or AdminAuthenticationForm,
            "template_name": self.login_template or "admin/login.html",
            "success_url": index_url,
        }
        request.current_app = self.name
        return LoginView.as_view(**defaults)(request)


admin_site = MailPilotAdminSite(name="admin")
