"""Shared admin UI helpers for homepage marketing sections."""

from __future__ import annotations

from django.utils.html import format_html


def _mkt_badge(label: str, tone: str) -> str:
    return format_html('<span class="mp-badge mp-badge-{}">{}</span>', tone, label)


def marketing_visibility_stats(qs) -> dict:
    total = qs.count()
    published = qs.filter(is_published=True).count()
    homepage = qs.filter(is_published=True, show_on_homepage=True).count()
    return {
        "total": total,
        "published": published,
        "homepage": homepage,
        "draft": total - published,
    }


def visibility_badges(*, is_published: bool, show_on_homepage: bool) -> str:
    from django.utils.safestring import mark_safe

    parts = [
        str(_mkt_badge("Live" if is_published else "Draft", "ok" if is_published else "muted")),
        str(
            _mkt_badge(
                "Homepage" if (show_on_homepage and is_published) else ("Off home" if show_on_homepage else "Inner"),
                "pro" if show_on_homepage and is_published else "muted",
            )
        ),
    ]
    return mark_safe(" ".join(parts))


class MarketingListUIMixin:
    """Ops-style toolbar + page title for marketing changelists."""

    list_before_template = "admin/core/marketing_toolbar.html"
    mp_mkt_title = "Marketing"
    mp_mkt_subtitle = "Homepage content"
    mp_mkt_site_url = "/"
    mp_mkt_settings_url_name = ""
    mp_mkt_settings_label = "Section settings"

    def get_mp_mkt_context(self, request) -> dict:
        qs = self.model.objects.all()
        ctx = {
            "title": self.mp_mkt_title,
            "mp_mkt": {
                "title": self.mp_mkt_title,
                "subtitle": self.mp_mkt_subtitle,
                "site_url": self.mp_mkt_site_url,
                "settings_url": "",
                "settings_label": self.mp_mkt_settings_label,
                **marketing_visibility_stats(qs),
            },
        }
        if self.mp_mkt_settings_url_name:
            from django.urls import reverse

            try:
                ctx["mp_mkt"]["settings_url"] = reverse(self.mp_mkt_settings_url_name)
            except Exception:
                ctx["mp_mkt"]["settings_url"] = ""
        return ctx

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self.get_mp_mkt_context(request))
        return super().changelist_view(request, extra_context=extra_context)
