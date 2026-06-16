from __future__ import annotations

from django.contrib.auth.views import LoginView
from django.http import HttpResponseRedirect
from django.urls import reverse
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
