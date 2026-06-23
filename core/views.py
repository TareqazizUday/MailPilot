from __future__ import annotations

import json
import logging
import os
import re
import threading
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from django.utils import timezone as dj_timezone
from typing import Any
from urllib.parse import quote, urljoin

from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit
from google_auth_oauthlib.flow import Flow
from werkzeug.utils import secure_filename

from core.access import check_api_access
from email_automation.gmail_auth import gmail_oauth_ready, gmail_oauth_try
from email_automation.gmail_client import GmailClient, gmail_retry_after_seconds, is_gmail_rate_limit_error
from email_automation.imap_mailbox import ImapMailbox, imap_inbox_ready
from email_automation.kb.embedder import embed_texts
from email_automation.kb.extract import (
    KBDocument,
    chunk_text,
    documents_from_json_upload,
    documents_from_text_upload,
    html_to_text,
    stable_doc_id,
)
from email_automation.kb.store import VectorStore, is_vector_db_configured
from scraper import (
    build_kb_export_bundle,
    build_website_crawl_export,
    crawl_site,
    documents_from_crawl_export,
    documents_from_kb_bundle,
    is_kb_bundle,
    delete_website_crawl_file,
    load_website_crawl_file,
    save_website_crawl_file,
)
from email_automation.settings import Settings
from email_automation.smtp_client import SMTPClient

from core import runtime
from core.audit import log_audit
from core.user_settings import user_data_dir
from core.contact_mail import send_contact_submission_emails
from core.models import ContactSubmission

logger = logging.getLogger("mailpilot.views")

_crawl_jobs_lock = threading.Lock()
_crawl_jobs: dict[int, dict[str, Any]] = {}


def _account_id_from_request(request) -> int | None:
    from core.mail_account_views import parse_account_id_from_request

    return parse_account_id_from_request(request)


def _resolve_mail_account(request):
    from core.mail_accounts import ensure_legacy_migrated, resolve_account

    ensure_legacy_migrated(request.user)
    aid = _account_id_from_request(request)
    return resolve_account(request.user, aid, require_enabled=False)


def _get_vector_store_for_user(user, account_id: int | None = None) -> VectorStore:
    from core.mail_accounts import ensure_legacy_migrated, resolve_account, tenant_id_for_account

    ensure_legacy_migrated(user)
    acc = resolve_account(user, account_id)
    effective = runtime.get_effective_settings(user, account_id=acc.id if acc else None)
    if acc:
        tid = tenant_id_for_account(user.id, acc.id)
    else:
        tid = str(user.id) if user is not None and getattr(user, "is_authenticated", False) else ""
    return VectorStore(settings=effective, tenant_id=tid)


def _user_settings_dict(request) -> dict[str, Any]:
    if not request.user.is_authenticated:
        return {}
    from core.models import UserMailSettings

    try:
        return dict(UserMailSettings.objects.get(user=request.user).settings_json or {})
    except UserMailSettings.DoesNotExist:
        return {}


def _smtp_imap_inbox_active(effective: Settings) -> bool:
    return effective.SEND_TRANSPORT == "smtp" and imap_inbox_ready(effective)


def _mailbox_connected_for_ui(
    effective: Settings, cfg: dict[str, Any], *, account_config: dict[str, Any] | None = None
) -> bool:
    """True if the user has a usable mailbox path for the *current* transport.

    IMAP credentials alone must not imply "connected" when SEND_TRANSPORT is still
    gmail_api (e.g. stale IMAP fields after saving SMTP once) - that broke the
    navbar showing Connected after Gmail OAuth disconnect.
    """
    transport = str(cfg.get("SEND_TRANSPORT") or effective.SEND_TRANSPORT or "").strip()
    if gmail_oauth_ready(effective):
        return True
    if transport == "smtp":
        if imap_inbox_ready(effective):
            return True
        acc_cfg = account_config if account_config is not None else {}
        return bool(acc_cfg.get("SMTP_LAST_TEST_OK") or cfg.get("SMTP_LAST_TEST_OK"))
    return False


def _oauth_callback_url(request, effective: Settings) -> str:
    explicit = (effective.OAUTH_REDIRECT_URI or "").strip()
    if explicit:
        return explicit.rstrip("/")
    # Prefer SITE_URL when behind a reverse proxy (IIS/ARR), because the backend
    # may see Host=127.0.0.1 and generate a localhost redirect URI otherwise.
    base = _public_base_url(request)
    return f"{base}{reverse('oauth_callback')}"


def server_error(request, exception=None):
    return render(request, "error.html", {"error": "Internal server error"}, status=500)


def favicon(request):
    from django.contrib.staticfiles import finders

    path = finders.find("favicon/favicon.ico")
    if not path:
        return HttpResponse(status=404)
    return FileResponse(open(path, "rb"), content_type="image/x-icon")


@require_GET
def healthz(request):
    from django.conf import settings as dj_settings

    ws = runtime.worker_state()
    celery_on = bool(getattr(dj_settings, "CELERY_BROKER_URL", "") or "")
    idle_count = 0
    try:
        from core.imap_idle import imap_idle_active_count, imap_idle_enabled

        idle_count = imap_idle_active_count() if imap_idle_enabled() else 0
    except Exception:
        idle_count = 0
    return JsonResponse(
        {
            "ok": True,
            "running": ws.running,
            "last_run_at": ws.last_run_at,
            "last_result": ws.last_result,
            "last_error": ws.last_error,
            "mail_poll_backend": runtime.mail_poll_backend(),
            "mail_poll_interval_seconds": runtime.mail_poll_interval_seconds(),
            "mail_poll_beat_seconds": getattr(dj_settings, "MAIL_POLL_BEAT_SECONDS", None) if celery_on else None,
            "imap_idle_enabled": idle_count > 0 or (
                (os.environ.get("IMAP_IDLE_ENABLED") or "true").strip().lower() in ("1", "true", "yes")
            ),
            "imap_idle_watchers": idle_count,
        }
    )


def _public_base_url(request) -> str:
    """Production site URL (SITE_URL) or fall back to this request."""
    from django.conf import settings as dj_settings

    u = (getattr(dj_settings, "SITE_URL", "") or "").strip().rstrip("/")
    if u:
        return u
    return request.build_absolute_uri("/").rstrip("/")


def _seo_landing_context(request, *, pricing_currency: str | None = None) -> dict[str, Any]:
    """Meta tags, canonical URL, and JSON-LD for the public landing page."""
    from django.conf import settings as dj_settings
    from core.pricing_currency import get_pricing_currency, seo_price_currency

    base = _public_base_url(request)
    canonical = f"{base}/"
    currency = seo_price_currency(pricing_currency or get_pricing_currency(request))

    og_image = (getattr(dj_settings, "OG_IMAGE_URL", "") or "").strip()
    if og_image:
        if og_image.startswith("http://") or og_image.startswith("https://"):
            og_image_abs = og_image
        else:
            og_image_abs = urljoin(f"{base}/", og_image.lstrip("/"))
    else:
        og_image_abs = ""

    meta_description = (
        "Automate Gmail and IMAP with AI: smart relevance filtering, RAG-grounded replies from your "
        "knowledge base, encrypted multi-tenant accounts, and optional Celery workers. "
        "MailPilot puts your inbox on autopilot."
    )
    page_title = "MailPilot | AI Email Automation for Gmail & IMAP with RAG"

    json_ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{canonical}#organization",
                "name": "MailPilot",
                "url": canonical,
                "description": meta_description,
            },
            {
                "@type": "SoftwareApplication",
                "name": "MailPilot",
                "applicationCategory": "BusinessApplication",
                "operatingSystem": "Web",
                "description": meta_description,
                "url": canonical,
                "author": {"@id": f"{canonical}#organization"},
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": currency},
            },
        ],
    }

    return {
        "seo_page_title": page_title,
        "seo_meta_description": meta_description,
        "seo_canonical_url": canonical,
        "seo_og_image": og_image_abs,
        "seo_json_ld": json.dumps(json_ld, ensure_ascii=True),
    }


@require_GET
def landing_page(request):
    """Public marketing home (also available to authenticated users)."""
    from core.marketing import (
        get_faq_settings,
        get_hero_settings,
        get_pricing_settings,
        how_it_works_steps_queryset,
        marketing_features_queryset,
        marketing_faq_queryset,
        marketing_hero_inbox_queryset,
        marketing_pricing_plans_queryset,
        marketing_reviews_queryset,
    )
    from core.pricing_currency import enrich_pricing_plans, pricing_context

    pc = pricing_context(request)
    ctx = _seo_landing_context(request, pricing_currency=pc["pricing_currency"])
    ctx.update(pc)
    ctx["contact_sent"] = request.GET.get("contact") == "sent"
    ctx["contact_error"] = (request.GET.get("contact_error") or "").strip()
    ctx["starter_expired"] = False
    ctx["current_plan_code"] = ""

    ctx["marketing_features"] = marketing_features_queryset(homepage_only=True)
    ctx["how_it_works_steps"] = how_it_works_steps_queryset(homepage_only=True)
    ctx["marketing_reviews"] = marketing_reviews_queryset(homepage_only=True)
    ctx["hero_settings"] = get_hero_settings()
    ctx["hero_inbox_items"] = marketing_hero_inbox_queryset(homepage_only=True)
    ctx["faq_settings"] = get_faq_settings()
    ctx["faq_items"] = marketing_faq_queryset(homepage_only=True)
    ctx["pricing_settings"] = get_pricing_settings()
    ctx["pricing_plans"] = enrich_pricing_plans(
        marketing_pricing_plans_queryset(homepage_only=True),
        currency=pc["pricing_currency"],
    )
    if request.user.is_authenticated:
        from core.user_settings import migrate_legacy_file_config_if_needed

        migrate_legacy_file_config_if_needed(request.user)
        effective = runtime.get_effective_settings(request.user)
        cfg = _user_settings_dict(request)
        ctx["connected"] = _mailbox_connected_for_ui(effective, cfg)
        try:
            from core.billing import get_or_create_subscription, is_starter_expired

            sub = get_or_create_subscription(request.user)
            ctx["current_plan_code"] = sub.plan_code
            ctx["starter_expired"] = is_starter_expired(sub)
        except Exception:
            ctx["current_plan_code"] = "starter"
            ctx["starter_expired"] = False
    return render(request, "landing.html", ctx)


def _client_ip(request: HttpRequest) -> str | None:
    xff = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if xff:
        return xff.split(",")[0].strip()[:45] or None
    raw = request.META.get("REMOTE_ADDR")
    return str(raw).strip()[:45] if raw else None


@csrf_protect
@ratelimit(key="ip", rate="10/h", method="POST", block=True)
@require_http_methods(["POST"])
def landing_contact(request):
    """Public contact form on the landing page."""
    name = (request.POST.get("name") or "").strip()[:120]
    email = (request.POST.get("email") or "").strip()[:254]
    phone = (request.POST.get("phone") or "").strip()[:32]
    message = (request.POST.get("message") or "").strip()[:2000]
    home = reverse("home")
    if not name or not message:
        return redirect(f"{home}?contact_error=invalid#contact")
    try:
        validate_email(email)
    except ValidationError:
        return redirect(f"{home}?contact_error=invalid#contact")

    submission = ContactSubmission.objects.create(
        name=name,
        email=email,
        phone=phone,
        message=message,
        ip_address=_client_ip(request),
    )
    log_audit(request, "landing_contact", f"id={submission.pk} email={email!r}")
    logger.info("Landing contact submission id=%s email=%s", submission.pk, email)

    team_ok, user_ok = send_contact_submission_emails(submission)
    submission.notified_team = team_ok
    submission.notified_user = user_ok
    submission.save(update_fields=["notified_team", "notified_user"])

    if not team_ok and not user_ok:
        return redirect(f"{home}?contact_error=mail#contact")

    return redirect(f"{home}?contact=sent#contact")


@require_GET
def robots_txt(request):
    base = _public_base_url(request)
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        "Disallow: /healthz\n"
        "Disallow: /dashboard\n"
        "Disallow: /setup\n"
        "Disallow: /profile\n"
        "\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


@require_GET
def sitemap_xml(request):
    from xml.sax.saxutils import escape

    base = _public_base_url(request)
    loc = escape(f"{base}/")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url>\n"
        f"    <loc>{loc}</loc>\n"
        "    <changefreq>weekly</changefreq>\n"
        "    <priority>1.0</priority>\n"
        "  </url>\n"
        "</urlset>\n"
    )
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")


@require_GET
def terms_page(request):
    from core.legal_content import get_terms_settings

    terms = get_terms_settings()
    ctx: dict[str, Any] = {"terms_page": terms}
    if request.user.is_authenticated:
        effective = runtime.get_effective_settings(request.user)
        cfg = _user_settings_dict(request)
        ctx["connected"] = _mailbox_connected_for_ui(effective, cfg)
    return render(request, "terms.html", ctx)


@require_GET
def privacy_page(request):
    from core.legal_content import get_privacy_settings

    privacy = get_privacy_settings()
    ctx: dict[str, Any] = {"privacy_page": privacy}
    if request.user.is_authenticated:
        effective = runtime.get_effective_settings(request.user)
        cfg = _user_settings_dict(request)
        ctx["connected"] = _mailbox_connected_for_ui(effective, cfg)
    return render(request, "privacy.html", ctx)


@require_GET
def pricing_page(request):
    """
    Clean URL for pricing (no `#pricing` fragment).
    This renders a dedicated pricing page that matches the landing aesthetic.
    """
    from core.marketing import get_pricing_settings, marketing_pricing_plans_queryset
    from core.pricing_currency import enrich_pricing_plans, pricing_context

    pc = pricing_context(request)
    ctx = _seo_landing_context(request, pricing_currency=pc["pricing_currency"])
    ctx.update(pc)
    if request.user.is_authenticated:
        effective = runtime.get_effective_settings(request.user)
        cfg = _user_settings_dict(request)
        ctx["connected"] = _mailbox_connected_for_ui(effective, cfg)
        try:
            from core.billing import get_or_create_subscription, is_starter_expired

            sub = get_or_create_subscription(request.user)
            ctx["current_plan_code"] = sub.plan_code
            ctx["starter_expired"] = is_starter_expired(sub)
        except Exception:
            ctx["current_plan_code"] = "starter"
            ctx["starter_expired"] = False
    else:
        ctx["current_plan_code"] = ""
        ctx["starter_expired"] = False
    ctx["pricing_settings"] = get_pricing_settings()
    ctx["pricing_plans"] = enrich_pricing_plans(
        marketing_pricing_plans_queryset(),
        currency=pc["pricing_currency"],
    )
    return render(request, "pricing.html", ctx)


@require_GET
def custom_plan_builder_page(request):
    """Interactive custom plan builder - adjust tokens & inboxes with live pricing."""
    from core.billing import custom_pricing_config
    from core.pricing_currency import pricing_context

    pc = pricing_context(request)
    ctx = _seo_landing_context(request, pricing_currency=pc["pricing_currency"])
    ctx.update(pc)
    config = custom_pricing_config(
        billing_interval=pc["billing_interval"],
        currency=pc["pricing_currency"],
    )
    ctx["custom_config"] = config
    ctx["custom_config_json"] = json.dumps(config)
    preset = (request.GET.get("preset") or "").strip().lower()
    initial_tokens = 2000
    initial_inboxes = 4
    for p in ctx["custom_config"].get("presets") or []:
        if p.get("id") == preset:
            initial_tokens = int(p.get("tokens") or initial_tokens)
            initial_inboxes = int(p.get("inboxes") or initial_inboxes)
            break
    ctx["initial_tokens"] = initial_tokens
    ctx["initial_inboxes"] = initial_inboxes
    if request.user.is_authenticated:
        effective = runtime.get_effective_settings(request.user)
        cfg = _user_settings_dict(request)
        ctx["connected"] = _mailbox_connected_for_ui(effective, cfg)
    return render(request, "pricing_custom.html", ctx)


@require_GET
def features_page(request):
    """
    Clean URL for features (no `#features` fragment).
    """
    ctx = _seo_landing_context(request)
    from core.marketing import marketing_features_queryset

    ctx["marketing_features"] = marketing_features_queryset()
    if request.user.is_authenticated:
        effective = runtime.get_effective_settings(request.user)
        cfg = _user_settings_dict(request)
        ctx["connected"] = _mailbox_connected_for_ui(effective, cfg)
    return render(request, "features.html", ctx)


@require_GET
def how_it_works_page(request):
    """
    Clean URL for "How it Works" (no fragment).
    """
    ctx = _seo_landing_context(request)
    from core.marketing import how_it_works_steps_queryset

    ctx["how_it_works_steps"] = how_it_works_steps_queryset()
    if request.user.is_authenticated:
        effective = runtime.get_effective_settings(request.user)
        cfg = _user_settings_dict(request)
        ctx["connected"] = _mailbox_connected_for_ui(effective, cfg)
    return render(request, "how_it_works.html", ctx)


@require_GET
def reviews_page(request):
    """
    Clean URL for reviews/testimonials (no fragment).
    """
    ctx = _seo_landing_context(request)
    from core.marketing import marketing_reviews_queryset

    ctx["marketing_reviews"] = marketing_reviews_queryset()
    if request.user.is_authenticated:
        effective = runtime.get_effective_settings(request.user)
        cfg = _user_settings_dict(request)
        ctx["connected"] = _mailbox_connected_for_ui(effective, cfg)
    return render(request, "reviews.html", ctx)


@login_required(login_url="/login")
@require_GET
def setup_page(request):
    logger.info("setup_page hit")
    from core.user_settings import migrate_legacy_file_config_if_needed

    migrate_legacy_file_config_if_needed(request.user)
    from core.mail_accounts import ensure_legacy_migrated, transport_summary

    ensure_legacy_migrated(request.user)
    effective = runtime.get_effective_settings(request.user)
    cfg = _user_settings_dict(request)
    connected = _mailbox_connected_for_ui(effective, cfg)
    oauth_redirect_uri = _oauth_callback_url(request, effective)
    highlight_account = (request.GET.get("account_id") or "").strip()
    return render(
        request,
        "setup.html",
        {
            "connected": connected,
            "gmail_oauth_connected": gmail_oauth_ready(effective),
            "gmail_address": (cfg.get("GMAIL_ADDRESS") or ""),
            "oauth_error": (request.GET.get("oauth_error") or "").strip(),
            "oauth_redirect_uri": oauth_redirect_uri,
            "transport_summary": transport_summary(request.user),
            "highlight_account_id": highlight_account,
        },
    )


@login_required(login_url="/login")
@require_GET
def dashboard_page(request):
    logger.info("dashboard_page hit path=%s", request.path)
    from core.user_settings import migrate_legacy_file_config_if_needed

    migrate_legacy_file_config_if_needed(request.user)
    effective = runtime.get_effective_settings(request.user)
    cfg = _user_settings_dict(request)
    connected = _mailbox_connected_for_ui(effective, cfg)
    inbox_ready = gmail_oauth_ready(effective) or imap_inbox_ready(effective)
    return render(
        request,
        "dashboard.html",
        {
            "connected": connected,
            "inbox_ready": inbox_ready,
        },
    )


@login_required(login_url="/login")
@require_http_methods(["GET", "POST"])
def profile_page(request):
    from core.models import UserProfile
    from django.core.files.uploadedfile import UploadedFile

    prof, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        # Avatar upload (optional)
        av: UploadedFile | None = request.FILES.get("avatar")  # type: ignore[assignment]
        if av and getattr(av, "name", ""):
            name = (av.name or "").lower()
            ok_ext = name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
            ok_mime = str(getattr(av, "content_type", "") or "").startswith("image/")
            max_bytes = 2 * 1024 * 1024
            if (not ok_ext) or (not ok_mime):
                from django.contrib import messages

                messages.error(request, "Avatar must be an image file (PNG/JPG/WEBP/GIF).")
                return redirect(reverse("profile"))
            if getattr(av, "size", 0) and av.size > max_bytes:
                from django.contrib import messages

                messages.error(request, "Avatar is too large. Max 2 MB.")
                return redirect(reverse("profile"))

            # Best-effort cleanup of old file
            try:
                if prof.avatar and prof.avatar.name and prof.avatar.storage.exists(prof.avatar.name):
                    prof.avatar.delete(save=False)
            except Exception:
                pass
            prof.avatar = av

        u = request.user
        u.first_name = (request.POST.get("first_name") or "").strip()[:150]
        u.last_name = (request.POST.get("last_name") or "").strip()[:150]
        u.email = (request.POST.get("email") or "").strip()[:254]
        u.save()
        prof.display_name = (request.POST.get("display_name") or "").strip()[:120]
        prof.phone = (request.POST.get("phone") or "").strip()[:32]
        prof.company = (request.POST.get("company") or "").strip()[:160]
        prof.timezone = (request.POST.get("timezone") or "UTC").strip()[:64]
        prof.notes = (request.POST.get("notes") or "").strip()[:2000]
        prof.save()
        log_audit(request, "profile_updated", "")
        from django.contrib import messages

        messages.success(request, "Profile saved.")
        return redirect(reverse("profile"))

    # Provide connection state for the app nav
    from core.user_settings import migrate_legacy_file_config_if_needed

    migrate_legacy_file_config_if_needed(request.user)
    effective = runtime.get_effective_settings(request.user)
    cfg = _user_settings_dict(request)
    connected = _mailbox_connected_for_ui(effective, cfg)

    # Avatar URL (avoid broken /media/... links if file is missing)
    avatar_url = ""
    try:
        if prof.avatar and prof.avatar.name and prof.avatar.storage.exists(prof.avatar.name):
            avatar_url = prof.avatar.url
    except Exception:
        avatar_url = ""

    billing: dict = {}
    bill_display: dict = {}
    try:
        from core.billing import get_or_create_subscription, profile_billing_display, usage_summary

        get_or_create_subscription(request.user)
        billing = usage_summary(request.user)
        bill_display = profile_billing_display(billing)
    except Exception:
        logger.exception("profile billing summary failed user=%s", request.user.pk)
        from core.billing import profile_billing_display

        bill_display = profile_billing_display(None)

    return render(
        request,
        "profile.html",
        {
            "profile": prof,
            "connected": connected,
            "is_edit": (request.GET.get("edit") or "").strip() == "1",
            "avatar_url": avatar_url,
            "billing": billing,
            "plan_activated": (request.GET.get("plan") or "").strip().lower() in ("starter", "pro", "custom"),
            **bill_display,
        },
    )


@login_required(login_url="/login")
@require_http_methods(["GET", "POST"])
def settings_page(request):
    # Provide connection state for the app nav
    from core.user_settings import migrate_legacy_file_config_if_needed

    migrate_legacy_file_config_if_needed(request.user)
    effective = runtime.get_effective_settings(request.user)
    cfg = _user_settings_dict(request)
    connected = _mailbox_connected_for_ui(effective, cfg)

    if request.method == "POST":
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            u = form.save()
            update_session_auth_hash(request, u)  # keep user signed in
            log_audit(request, "password_changed", "")
            from django.contrib import messages

            messages.success(request, "Password updated.")
            return redirect(reverse("settings"))
        else:
            from django.contrib import messages

            # Show the most useful error, without leaking internals.
            err = next(iter(form.errors.get("__all__", []) or []), None) or "Please correct the errors and try again."
            messages.error(request, err)
            return redirect(reverse("settings"))

    return render(
        request,
        "settings.html",
        {
            "connected": connected,
        },
    )


@require_GET
def api_billing_summary(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        from core.billing import usage_summary

        acc = _resolve_mail_account(request)
        return JsonResponse({"ok": True, "billing": usage_summary(request.user, account=acc)})
    except Exception as e:
        logger.exception("billing summary failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@require_http_methods(["POST"])
def api_billing_select_plan(request):
    """Activate a plan for the current user (Starter is free; Pro redirects to checkout)."""
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        body = json.loads(request.body.decode("utf-8") or "{}") if request.body else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    plan = str(body.get("plan") or "").strip().lower()
    from core.billing import (
        PLAN_CUSTOM,
        PLAN_PRO,
        PLAN_STARTER,
        get_or_create_subscription,
        is_starter_expired,
        set_subscription_plan,
        usage_summary,
    )
    from core.models import UserSubscription

    if plan == PLAN_PRO:
        from core.billing_interval import get_billing_interval, set_billing_interval
        from core.pricing_currency import append_checkout_query_params

        interval = set_billing_interval(request, body.get("billing_interval") or get_billing_interval(request))
        return JsonResponse(
            {
                "ok": True,
                "billing_interval": interval,
                "redirect": append_checkout_query_params(reverse("billing_checkout_pro"), request),
            }
        )
    if plan == PLAN_CUSTOM:
        from core.billing_interval import get_billing_interval, set_billing_interval
        from core.pricing_currency import append_checkout_query_params

        interval = set_billing_interval(request, body.get("billing_interval") or get_billing_interval(request))
        return JsonResponse(
            {
                "ok": True,
                "billing_interval": interval,
                "redirect": append_checkout_query_params(reverse("custom_plan_builder"), request),
            }
        )
    if plan != PLAN_STARTER:
        return JsonResponse({"ok": False, "error": "invalid_plan"}, status=400)
    try:
        sub = get_or_create_subscription(request.user)
        if is_starter_expired(sub):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "starter_trial_expired",
                    "upgrade_required": True,
                    "billing": usage_summary(request.user),
                    "redirect": reverse("pricing"),
                },
                status=403,
            )
        set_subscription_plan(sub, plan, status=UserSubscription.STATUS_ACTIVE)
        billing = usage_summary(request.user)
        return JsonResponse(
            {
                "ok": True,
                "plan": plan,
                "billing": billing,
                "redirect": f"{reverse('profile')}?plan={plan}",
            }
        )
    except Exception as e:
        logger.exception("billing select plan failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@require_GET
def api_billing_interval(request):
    """Return the billing interval pinned for this browser session."""
    from core.billing_interval import get_billing_interval

    interval = get_billing_interval(request)
    return JsonResponse({"ok": True, "interval": interval})


@require_GET
def api_billing_currency(request):
    """Return the pricing currency pinned for this browser session."""
    from core.pricing_currency import currency_label, currency_symbol, get_pricing_currency

    currency = get_pricing_currency(request)
    return JsonResponse(
        {
            "ok": True,
            "currency": currency,
            "label": currency_label(currency),
            "symbol": currency_symbol(currency),
        }
    )


@require_http_methods(["POST"])
def api_billing_set_currency(request):
    """Pin monthly/yearly pricing display currency for this session."""
    try:
        body = json.loads(request.body.decode("utf-8") or "{}") if request.body else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    from core.pricing_currency import currency_label, currency_symbol, set_pricing_currency

    currency = set_pricing_currency(request, str(body.get("currency") or ""))
    return JsonResponse(
        {
            "ok": True,
            "currency": currency,
            "label": currency_label(currency),
            "symbol": currency_symbol(currency),
        }
    )


@require_http_methods(["POST"])
def api_billing_set_interval(request):
    """Pin monthly/yearly billing interval for checkout (public - session only)."""
    try:
        body = json.loads(request.body.decode("utf-8") or "{}") if request.body else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    from core.billing_interval import interval_label, set_billing_interval

    interval = set_billing_interval(request, str(body.get("interval") or ""))
    return JsonResponse({"ok": True, "interval": interval, "label": interval_label(interval)})


@require_GET
def api_billing_custom_config(request):
    """Public pricing knobs for the custom plan builder UI."""
    from core.billing import custom_pricing_config
    from core.billing_interval import get_billing_interval
    from core.pricing_currency import get_pricing_currency

    interval = get_billing_interval(request)
    currency = get_pricing_currency(request)
    return JsonResponse(
        {
            "ok": True,
            "config": custom_pricing_config(billing_interval=interval, currency=currency),
        }
    )


@require_http_methods(["GET", "POST"])
def api_billing_custom_quote(request):
    """Preview or save a custom plan quote (server-side price validation)."""
    from core.billing import (
        CUSTOM_QUOTE_TTL_HOURS,
        clamp_custom_inputs,
        custom_daily_send_limit,
        custom_plan_quote_summary,
    )
    from core.models import CustomPlanQuote
    from core.billing_interval import get_billing_interval, set_billing_interval
    from core.pricing_currency import get_pricing_currency

    interval = get_billing_interval(request)
    currency = get_pricing_currency(request)
    if request.method == "GET":
        try:
            tokens = int(request.GET.get("tokens") or 2000)
            inboxes = int(request.GET.get("inboxes") or 4)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "invalid_input"}, status=400)
        raw_interval = request.GET.get("interval") or request.GET.get("billing_interval")
        if raw_interval:
            interval = set_billing_interval(request, raw_interval)
        return JsonResponse(
            {
                "ok": True,
                "quote": custom_plan_quote_summary(
                    tokens,
                    inboxes,
                    billing_interval=interval,
                    currency=currency,
                ),
            }
        )

    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        body = json.loads(request.body.decode("utf-8") or "{}") if request.body else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        tokens = int(body.get("tokens") or 2000)
        inboxes = int(body.get("inboxes") or 4)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "invalid_input"}, status=400)

    interval = set_billing_interval(request, body.get("billing_interval") or get_billing_interval(request))
    currency = get_pricing_currency(request)
    summary = custom_plan_quote_summary(
        tokens,
        inboxes,
        billing_interval=interval,
        currency=currency,
    )
    tok, boxes = clamp_custom_inputs(tokens, inboxes)
    price_cents = summary["price_cents"]
    now = dj_timezone.now()
    quote = CustomPlanQuote.objects.create(
        user=request.user,
        tokens=tok,
        inboxes=boxes,
        price_cents=price_cents,
        currency=currency,
        billing_interval=interval,
        daily_send_limit=custom_daily_send_limit(boxes),
        status=CustomPlanQuote.STATUS_DRAFT,
        expires_at=now + timedelta(hours=CUSTOM_QUOTE_TTL_HOURS),
    )
    from core.pricing_currency import append_checkout_query_params

    return JsonResponse(
        {
            "ok": True,
            "quote_id": quote.pk,
            "quote": summary,
            "checkout_url": append_checkout_query_params(
                reverse("billing_checkout_custom", args=[quote.pk]),
                request,
            ),
        }
    )


def _billing_checkout_summary(request, *, plan: str, quote=None) -> dict[str, Any]:
    from core.billing_interval import get_billing_interval, interval_label, interval_suffix
    from core.pricing_currency import format_cents, get_pricing_currency, normalize_currency, pro_checkout_cents

    interval = get_billing_interval(request)
    if plan == "pro":
        currency = get_pricing_currency(request)
        amount_cents = pro_checkout_cents(interval, currency)
        return {
            "plan": "pro",
            "title": "MailPilot Pro",
            "billing_interval": interval,
            "pricing_currency": currency,
            "interval_label": interval_label(interval),
            "interval_suffix": interval_suffix(interval),
            "amount_cents": amount_cents,
            "amount_display": format_cents(amount_cents, currency),
            "subtitle": f"1,000 tokens · 3 inboxes · {interval_label(interval).lower()}",
            "cancel_url": reverse("pricing"),
        }
    quote_interval = getattr(quote, "billing_interval", None) or interval
    currency = normalize_currency(getattr(quote, "currency", None) or get_pricing_currency(request))
    amount_cents = int(quote.price_cents)
    return {
        "plan": "custom",
        "title": "MailPilot Custom",
        "billing_interval": quote_interval,
        "pricing_currency": currency,
        "interval_label": interval_label(quote_interval),
        "interval_suffix": interval_suffix(quote_interval),
        "amount_cents": amount_cents,
        "amount_display": format_cents(amount_cents, currency),
        "subtitle": (
            f"{quote.tokens:,} tokens · {quote.inboxes} inbox(es) · "
            f"{interval_label(quote_interval).lower()}"
        ),
        "cancel_url": f"{reverse('custom_plan_builder')}?quote={quote.pk}",
        "quote_id": quote.pk,
    }


def _billing_resolve_checkout_target(request, *, plan_param: str = "", quote_param: str = ""):
    from core.billing_interval import set_billing_interval
    from core.models import CustomPlanQuote
    from core.pricing_currency import set_pricing_currency

    raw_interval = request.GET.get("interval") or request.GET.get("billing_interval")
    if raw_interval:
        set_billing_interval(request, raw_interval)
    raw_currency = request.GET.get("currency")
    if raw_currency:
        set_pricing_currency(request, raw_currency)

    quote_id = (quote_param or request.GET.get("quote") or request.POST.get("quote_id") or "").strip()
    plan = (plan_param or request.GET.get("plan") or request.POST.get("plan") or "").strip().lower()
    quote = None
    if quote_id.isdigit():
        quote = CustomPlanQuote.objects.filter(pk=int(quote_id), user=request.user).first()
        if quote is None:
            return None, None, redirect(f"{reverse('custom_plan_builder')}?billing=quote_not_found")
        if quote.status == CustomPlanQuote.STATUS_PAID:
            return None, None, redirect(f"{reverse('setup')}?billing=success")
        if quote.expires_at and quote.expires_at < dj_timezone.now():
            quote.status = CustomPlanQuote.STATUS_EXPIRED
            quote.save(update_fields=["status", "updated_at"])
            return None, None, redirect(f"{reverse('custom_plan_builder')}?billing=quote_expired")
        plan = "custom"
    if plan not in ("pro", "custom"):
        return None, None, redirect(f"{reverse('pricing')}?billing=invalid_plan")
    if plan == "custom" and quote is None:
        return None, None, redirect(f"{reverse('custom_plan_builder')}?billing=quote_not_found")
    return plan, quote, None


def _billing_begin_checkout(request, *, plan: str = "pro", quote=None):
    from core.payment_gateway import available_payment_providers

    providers = available_payment_providers()
    if not providers:
        if plan == "custom" and quote is not None:
            return redirect(f"{reverse('custom_plan_builder')}?billing=not_configured&quote={quote.pk}")
        return redirect(f"{reverse('pricing')}?billing=not_configured")
    if len(providers) > 1:
        from core.billing_interval import get_billing_interval
        from core.pricing_currency import get_pricing_currency

        interval = get_billing_interval(request)
        currency = get_pricing_currency(request)
        params = f"plan={plan}&interval={interval}&currency={currency}"
        if quote is not None:
            params = f"quote={quote.pk}&interval={interval}&currency={currency}"
        return redirect(f"{reverse('billing_choose_payment')}?{params}")
    return _billing_checkout_provider(request, providers[0], plan=plan, quote=quote)


def _billing_checkout_provider(request, provider: str, *, plan: str = "pro", quote=None):
    from core.payment_gateway import (
        PAYMENT_PAYPAL,
        PAYMENT_STRIPE,
        available_payment_providers,
        billing_demo_mode,
        paypal_available_at_checkout,
        stripe_checkout_ready,
    )

    if provider not in available_payment_providers():
        return redirect(f"{reverse('pricing')}?billing=invalid_provider")

    if provider == PAYMENT_STRIPE:
        from core.payment_gateway import billing_site_url_missing, stripe_checkout_block_reason

        if billing_site_url_missing():
            logger.warning("stripe checkout blocked: SITE_URL not set on production")
            target = reverse("custom_plan_builder") if plan == "custom" and quote else reverse("pricing")
            return redirect(f"{target}?billing=site_url_missing")
        block = stripe_checkout_block_reason()
        if block:
            logger.warning("stripe checkout blocked: %s", block)
            target = reverse("custom_plan_builder") if plan == "custom" and quote else reverse("pricing")
            return redirect(f"{target}?billing=stripe_not_ready")
        if stripe_checkout_ready():
            if plan == "custom":
                return _stripe_checkout_custom(request, quote)
            return _stripe_checkout_pro(request)
        if billing_demo_mode():
            return _billing_demo_checkout_redirect(request, plan=plan, quote=quote, provider=PAYMENT_STRIPE)

    if provider == PAYMENT_PAYPAL:
        from core.payment_gateway import billing_site_url_missing, paypal_checkout_ready

        if not paypal_available_at_checkout():
            return redirect(f"{reverse('pricing')}?billing=invalid_provider")
        if billing_site_url_missing() and paypal_checkout_ready():
            logger.warning("paypal checkout blocked: SITE_URL not set on production")
            target = reverse("custom_plan_builder") if plan == "custom" and quote else reverse("pricing")
            return redirect(f"{target}?billing=site_url_missing")
        if paypal_checkout_ready():
            if plan == "custom":
                return _paypal_checkout_custom(request, quote)
            return _paypal_checkout_pro(request)
        if billing_demo_mode():
            return _billing_demo_checkout_redirect(request, plan=plan, quote=quote, provider=PAYMENT_PAYPAL)

    if plan == "custom" and quote is not None:
        return redirect(f"{reverse('custom_plan_builder')}?billing=not_configured&quote={quote.pk}")
    return redirect(f"{reverse('pricing')}?billing=not_configured")


def _billing_demo_checkout_redirect(request, *, plan: str, quote=None, provider: str):
    from core.billing_interval import get_billing_interval
    from core.models import CustomPlanQuote
    from core.pricing_currency import get_pricing_currency

    interval = get_billing_interval(request)
    currency = get_pricing_currency(request)
    if quote is not None:
        quote.status = CustomPlanQuote.STATUS_PENDING
        quote.stripe_session_id = quote.stripe_session_id or f"demo_{quote.pk}"
        quote.save(update_fields=["status", "stripe_session_id", "updated_at"])
        return redirect(
            f"{reverse('billing_checkout_pay')}?quote={quote.pk}&provider={provider}&interval={interval}&currency={currency}"
        )
    return redirect(
        f"{reverse('billing_checkout_pay')}?plan={plan}&provider={provider}&interval={interval}&currency={currency}"
    )


def _stripe_checkout_pro(request):
    from core.billing_interval import get_billing_interval, stripe_recurring_interval
    from core.payment_gateway import get_stripe_credentials
    from core.pricing_currency import CURRENCY_USD, get_pricing_currency, pro_checkout_cents, stripe_currency_code

    creds = get_stripe_credentials()
    secret = creds.secret_key
    interval = get_billing_interval(request)
    currency = stripe_currency_code(get_pricing_currency(request))
    try:
        import requests

        base = _public_base_url(request)
        data = {
            "mode": "subscription",
            "payment_method_types[0]": "card",
            "line_items[0][quantity]": "1",
            "success_url": f"{base}{reverse('setup')}?billing=success",
            "cancel_url": f"{base}{reverse('pricing')}?billing=cancelled",
            "client_reference_id": str(request.user.id),
            "customer_email": (request.user.email or "").strip(),
            "metadata[user_id]": str(request.user.id),
            "metadata[billing_interval]": interval,
            "metadata[pricing_currency]": currency,
        }
        use_price_id = currency == CURRENCY_USD
        if interval == "yearly" and use_price_id and creds.price_pro_yearly:
            data["line_items[0][price]"] = creds.price_pro_yearly
        elif interval == "yearly":
            amount = pro_checkout_cents(interval, currency)
            data.update(
                {
                    "line_items[0][price_data][currency]": currency,
                    "line_items[0][price_data][unit_amount]": str(amount),
                    "line_items[0][price_data][recurring][interval]": "year",
                    "line_items[0][price_data][product_data][name]": "MailPilot Pro",
                    "line_items[0][price_data][product_data][description]": "1,000 tokens · 3 inboxes · yearly",
                }
            )
        elif use_price_id and creds.price_pro_monthly:
            data["line_items[0][price]"] = creds.price_pro_monthly
        else:
            amount = pro_checkout_cents(interval, currency)
            data.update(
                {
                    "line_items[0][price_data][currency]": currency,
                    "line_items[0][price_data][unit_amount]": str(amount),
                    "line_items[0][price_data][recurring][interval]": stripe_recurring_interval(interval),
                    "line_items[0][price_data][product_data][name]": "MailPilot Pro",
                    "line_items[0][price_data][product_data][description]": "1,000 tokens · 3 inboxes · monthly",
                }
            )
        resp = requests.post(
            "https://api.stripe.com/v1/checkout/sessions",
            data=data,
            auth=(secret, ""),
            timeout=20,
        )
        payload = resp.json() if resp.content else {}
        if not resp.ok:
            logger.warning("stripe checkout failed: %s", payload or resp.text)
            return redirect(f"{reverse('pricing')}?billing=checkout_error")
        url = str(payload.get("url") or "").strip()
        if not url:
            return redirect(f"{reverse('pricing')}?billing=checkout_error")
        return redirect(url)
    except Exception as e:
        logger.exception("stripe checkout exception: %s", e)
        return redirect(f"{reverse('pricing')}?billing=checkout_error")


def _stripe_checkout_custom(request, quote):
    from core.billing_interval import stripe_recurring_interval
    from core.payment_gateway import get_stripe_credentials
    from core.pricing_currency import normalize_currency, stripe_currency_code

    creds = get_stripe_credentials()
    try:
        import requests

        base = _public_base_url(request)
        amount = int(quote.price_cents)
        interval = getattr(quote, "billing_interval", None) or "monthly"
        currency = stripe_currency_code(normalize_currency(getattr(quote, "currency", None) or "usd"))
        period = "yr" if interval == "yearly" else "mo"
        label = (
            f"MailPilot Custom - {quote.tokens:,} tokens · "
            f"{quote.inboxes} inbox(es)/{period}"
        )
        data = {
            "mode": "subscription",
            "payment_method_types[0]": "card",
            "line_items[0][price_data][currency]": currency,
            "line_items[0][price_data][unit_amount]": str(amount),
            "line_items[0][price_data][recurring][interval]": stripe_recurring_interval(interval),
            "line_items[0][price_data][product_data][name]": "MailPilot Custom Plan",
            "line_items[0][price_data][product_data][description]": label[:500],
            "line_items[0][quantity]": "1",
            "success_url": f"{base}{reverse('setup')}?billing=success",
            "cancel_url": f"{base}{reverse('custom_plan_builder')}?billing=cancelled&quote={quote.pk}",
            "client_reference_id": str(request.user.id),
            "customer_email": (request.user.email or "").strip(),
            "metadata[user_id]": str(request.user.id),
            "metadata[plan_type]": "custom",
            "metadata[quote_id]": str(quote.pk),
            "metadata[pricing_currency]": currency,
            "metadata[tokens]": str(quote.tokens),
            "metadata[inboxes]": str(quote.inboxes),
        }
        resp = requests.post(
            "https://api.stripe.com/v1/checkout/sessions",
            data=data,
            auth=(creds.secret_key, ""),
            timeout=20,
        )
        payload = resp.json() if resp.content else {}
        if not resp.ok:
            logger.warning("stripe custom checkout failed: %s", payload or resp.text)
            return redirect(f"{reverse('custom_plan_builder')}?billing=checkout_error")
        url = str(payload.get("url") or "").strip()
        session_id = str(payload.get("id") or "").strip()
        if not url:
            return redirect(f"{reverse('custom_plan_builder')}?billing=checkout_error")
        quote.status = CustomPlanQuote.STATUS_PENDING
        quote.stripe_session_id = session_id
        quote.save(update_fields=["status", "stripe_session_id", "updated_at"])
        return redirect(url)
    except Exception as e:
        logger.exception("stripe custom checkout exception: %s", e)
        return redirect(f"{reverse('custom_plan_builder')}?billing=checkout_error")


def _paypal_checkout_pro(request):
    from core.billing_interval import get_billing_interval
    from core.payment_gateway import PAYMENT_PAYPAL, get_paypal_credentials
    from core.paypal_api import (
        PayPalAPIError,
        paypal_build_custom_id,
        paypal_create_subscription,
        paypal_approval_url,
        paypal_resolve_plan_id,
    )
    from core.pricing_currency import get_pricing_currency, pro_checkout_cents, stripe_currency_code

    creds = get_paypal_credentials()
    if not creds:
        return redirect(f"{reverse('pricing')}?billing=not_configured")
    interval = get_billing_interval(request)
    currency = stripe_currency_code(get_pricing_currency(request))
    amount_cents = pro_checkout_cents(interval, currency)
    period = "Yearly" if interval == "yearly" else "Monthly"
    try:
        base = _public_base_url(request)
        plan_id = paypal_resolve_plan_id(
            creds,
            name=f"MailPilot Pro {period}",
            description=f"MailPilot Pro · 1,000 tokens · 3 inboxes · {period.lower()}",
            amount_cents=amount_cents,
            currency=currency,
            interval=interval,
        )
        custom_id = paypal_build_custom_id(
            user_id=request.user.id,
            plan="pro",
            interval=interval,
        )
        sub_payload = paypal_create_subscription(
            creds,
            plan_id=plan_id,
            email=(request.user.email or "").strip(),
            return_url=f"{base}{reverse('billing_paypal_return')}?plan=pro",
            cancel_url=f"{base}{reverse('pricing')}?billing=cancelled",
            custom_id=custom_id,
        )
        url = paypal_approval_url(sub_payload)
        if not url:
            return redirect(f"{reverse('pricing')}?billing=checkout_error")
        request.session["paypal_checkout"] = {
            "provider": PAYMENT_PAYPAL,
            "plan": "pro",
            "interval": interval,
            "currency": currency,
            "subscription_id": str(sub_payload.get("id") or ""),
        }
        request.session.modified = True
        return redirect(url)
    except PayPalAPIError as e:
        logger.warning("paypal pro checkout failed: %s %s", e.code, e.payload)
        return redirect(f"{reverse('pricing')}?billing=checkout_error")
    except Exception as e:
        logger.exception("paypal pro checkout exception: %s", e)
        return redirect(f"{reverse('pricing')}?billing=checkout_error")


def _paypal_checkout_custom(request, quote):
    from core.billing_interval import interval_label
    from core.models import CustomPlanQuote
    from core.payment_gateway import PAYMENT_PAYPAL, get_paypal_credentials
    from core.paypal_api import (
        PayPalAPIError,
        paypal_build_custom_id,
        paypal_create_subscription,
        paypal_approval_url,
        paypal_ensure_billing_plan,
    )
    from core.pricing_currency import normalize_currency, stripe_currency_code

    creds = get_paypal_credentials()
    if not creds:
        return redirect(f"{reverse('custom_plan_builder')}?billing=not_configured&quote={quote.pk}")
    interval = getattr(quote, "billing_interval", None) or "monthly"
    currency = stripe_currency_code(normalize_currency(getattr(quote, "currency", None) or "usd"))
    amount_cents = int(quote.price_cents)
    period = interval_label(interval).lower()
    label = f"MailPilot Custom - {quote.tokens:,} tokens · {quote.inboxes} inbox(es) · {period}"
    try:
        base = _public_base_url(request)
        plan_id = paypal_ensure_billing_plan(
            creds,
            name=f"MailPilot Custom ({quote.pk})",
            description=label[:127],
            amount_cents=amount_cents,
            currency=currency,
            interval=interval,
        )
        custom_id = paypal_build_custom_id(
            user_id=request.user.id,
            plan="custom",
            interval=interval,
            quote_id=quote.pk,
        )
        sub_payload = paypal_create_subscription(
            creds,
            plan_id=plan_id,
            email=(request.user.email or "").strip(),
            return_url=f"{base}{reverse('billing_paypal_return')}?plan=custom&quote={quote.pk}",
            cancel_url=f"{base}{reverse('custom_plan_builder')}?billing=cancelled&quote={quote.pk}",
            custom_id=custom_id,
        )
        url = paypal_approval_url(sub_payload)
        subscription_id = str(sub_payload.get("id") or "").strip()
        if not url:
            return redirect(f"{reverse('custom_plan_builder')}?billing=checkout_error&quote={quote.pk}")
        quote.status = CustomPlanQuote.STATUS_PENDING
        quote.stripe_session_id = subscription_id or quote.stripe_session_id
        quote.save(update_fields=["status", "stripe_session_id", "updated_at"])
        request.session["paypal_checkout"] = {
            "provider": PAYMENT_PAYPAL,
            "plan": "custom",
            "quote_id": quote.pk,
            "subscription_id": subscription_id,
        }
        request.session.modified = True
        return redirect(url)
    except PayPalAPIError as e:
        logger.warning("paypal custom checkout failed: %s %s", e.code, e.payload)
        return redirect(f"{reverse('custom_plan_builder')}?billing=checkout_error&quote={quote.pk}")
    except Exception as e:
        logger.exception("paypal custom checkout exception: %s", e)
        return redirect(f"{reverse('custom_plan_builder')}?billing=checkout_error&quote={quote.pk}")


def _paypal_finalize_subscription(request, subscription_id: str):
    from core.billing import PLAN_PRO, activate_custom_plan_quote, get_or_create_subscription, set_subscription_plan
    from core.models import CustomPlanQuote, UserSubscription
    from core.payment_gateway import PAYMENT_PAYPAL, get_paypal_credentials
    from core.paypal_api import (
        PayPalAPIError,
        paypal_get_subscription,
        paypal_parse_custom_id,
        paypal_subscription_is_paid,
    )

    creds = get_paypal_credentials()
    if not creds or not subscription_id:
        return None, redirect(f"{reverse('pricing')}?billing=checkout_error")

    try:
        payload = paypal_get_subscription(creds, subscription_id)
    except PayPalAPIError:
        return None, redirect(f"{reverse('pricing')}?billing=checkout_error")

    status = str(payload.get("status") or "")
    if not paypal_subscription_is_paid(status):
        return None, redirect(f"{reverse('pricing')}?billing=checkout_error")

    meta = paypal_parse_custom_id(str(payload.get("custom_id") or ""))
    user_id = meta.get("uid") or ""
    if not user_id.isdigit() or int(user_id) != request.user.id:
        return None, redirect(f"{reverse('pricing')}?billing=checkout_error")

    plan = (meta.get("plan") or "pro").strip().lower()
    sub = get_or_create_subscription(request.user)
    sub.payment_provider = PAYMENT_PAYPAL
    sub.paypal_subscription_id = subscription_id

    if plan == "custom":
        quote_id = (meta.get("quote") or "").strip()
        quote = None
        if quote_id.isdigit():
            quote = CustomPlanQuote.objects.filter(pk=int(quote_id), user=request.user).first()
        if quote is None:
            return None, redirect(f"{reverse('custom_plan_builder')}?billing=quote_not_found")
        activate_custom_plan_quote(request.user, quote)
        quote.stripe_session_id = subscription_id
        quote.save(update_fields=["stripe_session_id", "updated_at"])
        sub.save(update_fields=["payment_provider", "paypal_subscription_id", "updated_at"])
        return quote, redirect(f"{reverse('setup')}?billing=success&provider=paypal")

    sub.paid_at = dj_timezone.now()
    set_subscription_plan(sub, PLAN_PRO, status=UserSubscription.STATUS_ACTIVE)
    return sub, redirect(f"{reverse('setup')}?billing=success&provider=paypal")


@login_required(login_url="/login")
@require_http_methods(["GET"])
def billing_paypal_return(request):
    """Return URL after PayPal subscription approval."""
    subscription_id = (
        (request.GET.get("subscription_id") or "").strip()
        or (request.session.get("paypal_checkout") or {}).get("subscription_id", "")
    )
    if not subscription_id:
        return redirect(f"{reverse('pricing')}?billing=checkout_error")
    _, response = _paypal_finalize_subscription(request, subscription_id)
    request.session.pop("paypal_checkout", None)
    request.session.modified = True
    return response


@login_required(login_url="/login")
@require_http_methods(["GET", "POST"])
def billing_choose_payment(request):
    """Let the user pick Stripe or PayPal when more than one provider is available."""
    from core.payment_gateway import (
        PAYMENT_PAYPAL,
        PAYMENT_STRIPE,
        available_payment_providers,
        billing_choose_payment_is_demo,
        stripe_checkout_block_reason,
    )

    plan, quote, deny = _billing_resolve_checkout_target(request)
    if deny is not None:
        return deny

    providers = available_payment_providers()
    if not providers:
        return _billing_begin_checkout(request, plan=plan, quote=quote)
    if len(providers) == 1:
        return _billing_checkout_provider(request, providers[0], plan=plan, quote=quote)

    summary = _billing_checkout_summary(request, plan=plan, quote=quote)

    if request.method == "POST":
        provider = (request.POST.get("provider") or "").strip().lower()
        if provider not in providers:
            summary["error"] = "Choose a payment method to continue."
        else:
            return _billing_checkout_provider(request, provider, plan=plan, quote=quote)

    stripe_block = stripe_checkout_block_reason()
    provider_options = [
        {
            "code": PAYMENT_STRIPE,
            "label": "Credit or debit card",
            "hint": (
                "Live account pending activation — use test keys locally"
                if stripe_block
                else "Visa, Mastercard, Amex and more"
            ),
        },
        {
            "code": PAYMENT_PAYPAL,
            "label": "PayPal",
            "hint": "Pay with balance, bank, or linked card",
        },
    ]
    provider_options = [opt for opt in provider_options if opt["code"] in providers]

    return render(
        request,
        "billing_choose_payment.html",
        {
            **summary,
            "amount_usd": summary.get("amount_display") or f"{summary['amount_cents'] / 100:.2f}",
            "provider_options": provider_options,
            "user_email": (request.user.email or "").strip(),
            "show_demo_banner": billing_choose_payment_is_demo(),
        },
    )


@login_required(login_url="/login")
@require_http_methods(["GET", "POST"])
def billing_checkout_pro(request):
    """Start Pro checkout - routes to provider choice or Stripe Checkout."""
    plan, quote, deny = _billing_resolve_checkout_target(request, plan_param="pro")
    if deny is not None:
        return deny
    return _billing_begin_checkout(request, plan=plan, quote=quote)


@login_required(login_url="/login")
@require_GET
def billing_custom_request(request):
    """Open the interactive custom plan builder."""
    preset = (request.GET.get("preset") or "").strip()
    if preset:
        return redirect(f"{reverse('custom_plan_builder')}?preset={preset}")
    return redirect(reverse("custom_plan_builder"))


@login_required(login_url="/login")
@require_GET
def billing_checkout_custom(request, quote_id: int):
    """Checkout for a saved custom plan quote - routes to provider choice or Stripe."""
    plan, quote, deny = _billing_resolve_checkout_target(request, quote_param=str(quote_id))
    if deny is not None:
        return deny
    return _billing_begin_checkout(request, plan=plan, quote=quote)


@login_required(login_url="/login")
@require_GET
def billing_demo_checkout(request):
    """Simulated checkout for local demo (Stripe or PayPal UI)."""
    from core.payment_gateway import PAYMENT_PAYPAL, PAYMENT_STRIPE, billing_demo_mode, provider_label

    if not billing_demo_mode():
        return redirect(f"{reverse('pricing')}?billing=not_configured")

    plan, quote, deny = _billing_resolve_checkout_target(request)
    if deny is not None:
        return deny

    provider = (request.GET.get("provider") or PAYMENT_STRIPE).strip().lower()
    if provider not in (PAYMENT_STRIPE, PAYMENT_PAYPAL):
        provider = PAYMENT_STRIPE

    summary = _billing_checkout_summary(request, plan=plan, quote=quote)
    return render(
        request,
        "billing_demo_checkout.html",
        {
            **summary,
            "quote_id": quote.pk if quote else "",
            "amount_usd": summary.get("amount_display") or f"{summary['amount_cents'] / 100:.2f}",
            "user_email": (request.user.email or "").strip(),
            "provider": provider,
            "provider_label": provider_label(provider),
        },
    )


@login_required(login_url="/login")
@require_POST
@csrf_protect
def billing_demo_complete(request):
    """Complete a demo checkout - activates Pro or Custom without a live gateway."""
    from core.billing import PLAN_PRO, activate_custom_plan_quote, get_or_create_subscription, set_subscription_plan
    from core.models import CustomPlanQuote, UserSubscription
    from core.payment_gateway import PAYMENT_PAYPAL, PAYMENT_STRIPE, billing_demo_mode

    if not billing_demo_mode():
        return JsonResponse({"ok": False, "error": "demo_disabled"}, status=403)

    plan = (request.POST.get("plan") or "").strip().lower()
    quote_id = (request.POST.get("quote_id") or "").strip()
    provider = (request.POST.get("provider") or PAYMENT_STRIPE).strip().lower()
    if provider not in (PAYMENT_STRIPE, PAYMENT_PAYPAL):
        provider = PAYMENT_STRIPE

    if plan == "pro":
        sub = get_or_create_subscription(request.user)
        set_subscription_plan(sub, PLAN_PRO, status=UserSubscription.STATUS_ACTIVE)
        sub.paid_at = dj_timezone.now()
        sub.payment_provider = provider
        if provider == PAYMENT_PAYPAL:
            sub.paypal_subscription_id = sub.paypal_subscription_id or f"demo_pp_pro_{request.user.id}"
        else:
            sub.stripe_customer_id = sub.stripe_customer_id or f"demo_cus_{request.user.id}"
            sub.stripe_subscription_id = sub.stripe_subscription_id or f"demo_sub_pro_{request.user.id}"
        sub.save(
            update_fields=[
                "paid_at",
                "payment_provider",
                "stripe_customer_id",
                "stripe_subscription_id",
                "paypal_subscription_id",
                "updated_at",
            ]
        )
    elif plan == "custom" and quote_id.isdigit():
        quote = CustomPlanQuote.objects.filter(pk=int(quote_id), user=request.user).first()
        if quote is None:
            return redirect(f"{reverse('custom_plan_builder')}?billing=quote_not_found")
        activate_custom_plan_quote(request.user, quote)
        sub = get_or_create_subscription(request.user)
        sub.payment_provider = provider
        if provider == PAYMENT_PAYPAL:
            sub.paypal_subscription_id = sub.paypal_subscription_id or f"demo_pp_custom_{quote.pk}"
        else:
            sub.stripe_customer_id = sub.stripe_customer_id or f"demo_cus_{request.user.id}"
            sub.stripe_subscription_id = sub.stripe_subscription_id or f"demo_sub_custom_{quote.pk}"
        sub.save(
            update_fields=[
                "payment_provider",
                "stripe_customer_id",
                "stripe_subscription_id",
                "paypal_subscription_id",
                "updated_at",
            ]
        )
    else:
        return redirect(f"{reverse('pricing')}?billing=invalid_plan")

    return redirect(f"{reverse('setup')}?billing=success&demo=1&provider={provider}")


@login_required(login_url="/login")
@require_http_methods(["GET", "POST"])
def billing_portal(request):
    from core.payment_gateway import get_stripe_credentials

    creds = get_stripe_credentials()
    if not creds or not creds.secret_key:
        return redirect(f"{reverse('settings')}?billing=not_configured")
    secret = creds.secret_key
    try:
        from core.billing import get_or_create_subscription

        sub = get_or_create_subscription(request.user)
        customer_id = (sub.stripe_customer_id or "").strip()
        if not customer_id:
            return redirect(f"{reverse('pricing')}?billing=no_customer")
        import requests

        base = _public_base_url(request)
        resp = requests.post(
            "https://api.stripe.com/v1/billing_portal/sessions",
            data={"customer": customer_id, "return_url": f"{base}{reverse('settings')}"},
            auth=(secret, ""),
            timeout=20,
        )
        payload = resp.json() if resp.content else {}
        url = str(payload.get("url") or "").strip()
        if not resp.ok or not url:
            logger.warning("stripe portal failed: %s", payload or resp.text)
            return redirect(f"{reverse('settings')}?billing=portal_error")
        return redirect(url)
    except Exception as e:
        logger.exception("stripe portal exception: %s", e)
        return redirect(f"{reverse('settings')}?billing=portal_error")


def _stripe_signature_ok(raw: bytes, sig_header: str, secret: str) -> bool:
    if not secret:
        return True
    parts: dict[str, str] = {}
    for chunk in (sig_header or "").split(","):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            parts[k.strip()] = v.strip()
    ts = parts.get("t")
    v1 = parts.get("v1")
    if not ts or not v1:
        return False
    signed = f"{ts}.{raw.decode('utf-8', errors='replace')}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


@csrf_exempt
@require_http_methods(["POST"])
def billing_stripe_webhook(request):
    from core.payment_gateway import get_stripe_credentials

    raw = request.body or b""
    creds = get_stripe_credentials()
    webhook_secret = (creds.webhook_secret if creds else "") or (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    if webhook_secret and not _stripe_signature_ok(raw, request.headers.get("Stripe-Signature", ""), webhook_secret):
        return JsonResponse({"ok": False, "error": "invalid_signature"}, status=400)
    try:
        event = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)
    try:
        from django.contrib.auth.models import User
        from core.billing import get_or_create_subscription, set_subscription_plan

        etype = str(event.get("type") or "")
        obj = ((event.get("data") or {}).get("object") or {}) if isinstance(event.get("data"), dict) else {}
        user_id = (
            str((obj.get("metadata") or {}).get("user_id") or "").strip()
            or str(obj.get("client_reference_id") or "").strip()
        )
        user = User.objects.filter(pk=int(user_id)).first() if user_id.isdigit() else None
        if user is None and obj.get("customer"):
            from core.models import UserSubscription

            sub = UserSubscription.objects.filter(stripe_customer_id=str(obj.get("customer"))).select_related("user").first()
            user = sub.user if sub else None
        if user is None:
            return JsonResponse({"ok": True, "ignored": "unknown_user"})
        sub = get_or_create_subscription(user)
        meta = (obj.get("metadata") or {}) if isinstance(obj.get("metadata"), dict) else {}
        plan_type = str(meta.get("plan_type") or "pro").strip().lower()

        if etype == "checkout.session.completed":
            if plan_type == "custom":
                from core.billing import activate_custom_plan_quote
                from core.models import CustomPlanQuote

                quote_id = str(meta.get("quote_id") or "").strip()
                quote = None
                if quote_id.isdigit():
                    quote = CustomPlanQuote.objects.filter(pk=int(quote_id), user=user).first()
                if quote is None:
                    try:
                        tokens = int(meta.get("tokens") or 0)
                        inboxes = int(meta.get("inboxes") or 0)
                    except (TypeError, ValueError):
                        tokens, inboxes = 0, 0
                    if tokens and inboxes:
                        from core.billing import apply_custom_limits

                        apply_custom_limits(sub, tokens=tokens, inboxes=inboxes)
                        sub.paid_at = dj_timezone.now()
                else:
                    activate_custom_plan_quote(user, quote)
                sub.stripe_customer_id = str(obj.get("customer") or sub.stripe_customer_id or "")
                sub.stripe_subscription_id = str(obj.get("subscription") or sub.stripe_subscription_id or "")
            else:
                set_subscription_plan(sub, "pro", status="active")
                sub.stripe_customer_id = str(obj.get("customer") or sub.stripe_customer_id or "")
                sub.stripe_subscription_id = str(obj.get("subscription") or sub.stripe_subscription_id or "")
                sub.paid_at = dj_timezone.now()
        elif etype in ("customer.subscription.updated", "customer.subscription.created"):
            code = "custom" if plan_type == "custom" or sub.plan_code == "custom" else "pro"
            set_subscription_plan(
                sub,
                code,
                status="active" if str(obj.get("status") or "") in ("active", "trialing") else "past_due",
            )
            sub.stripe_customer_id = str(obj.get("customer") or sub.stripe_customer_id or "")
            sub.stripe_subscription_id = str(obj.get("id") or sub.stripe_subscription_id or "")
            if obj.get("current_period_start"):
                sub.current_period_start = datetime.fromtimestamp(
                    int(obj["current_period_start"]),
                    tz=timezone.utc,
                )
            if obj.get("current_period_end"):
                sub.current_period_end = datetime.fromtimestamp(
                    int(obj["current_period_end"]),
                    tz=timezone.utc,
                )
        elif etype == "customer.subscription.deleted":
            set_subscription_plan(sub, "starter", status="canceled")
        sub.save()
        return JsonResponse({"ok": True})
    except Exception as e:
        logger.exception("stripe webhook failed: %s", e)
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@csrf_exempt
def api_setup_credentials(request):
    logger.info("api_setup_credentials hit")
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

    gmail_address = (request.POST.get("gmail_address") or "").strip()
    if not gmail_address:
        return JsonResponse({"ok": False, "error": "Missing gmail_address"}, status=400)

    secret_file = request.FILES.get("client_secret")
    if secret_file is None or not getattr(secret_file, "name", ""):
        return JsonResponse({"ok": False, "error": "Missing client_secret.json file"}, status=400)

    filename = secure_filename(secret_file.name)
    if not filename.lower().endswith(".json"):
        return JsonResponse({"ok": False, "error": "client_secret file must be .json"}, status=400)

    from core.user_settings import save_client_secret_json, save_settings_patch

    raw = b"".join(secret_file.chunks())
    from core.mail_accounts import TRANSPORT_GMAIL, create_account, ensure_legacy_migrated, resolve_account

    ensure_legacy_migrated(request.user)
    acc = resolve_account(request.user, transport=TRANSPORT_GMAIL)
    if acc is None:
        acc = create_account(request.user, transport=TRANSPORT_GMAIL, gmail_address=gmail_address)
    save_client_secret_json(request.user, raw.decode("utf-8"))
    from core.mail_accounts import patch_account_config, save_account_client_secret

    save_account_client_secret(acc, raw.decode("utf-8"))
    patch_account_config(acc, {"GMAIL_ADDRESS": gmail_address})
    request.session["oauth_account_id"] = acc.id
    return redirect(reverse("oauth_start"))


@login_required(login_url="/login")
@require_GET
def oauth_start(request):
    try:
        logger.info("oauth_start hit")
        from core.mail_accounts import ensure_legacy_migrated, resolve_account

        ensure_legacy_migrated(request.user)
        account_id = request.session.get("oauth_account_id")
        acc = resolve_account(request.user, account_id)
        effective = runtime.get_effective_settings(request.user, account_id=acc.id if acc else None)
        client_secret_path = effective.GOOGLE_CLIENT_SECRET_FILE
        if not os.path.exists(client_secret_path):
            return JsonResponse({"ok": False, "error": "client_secret.json missing"}, status=400)

        callback_url = _oauth_callback_url(request, effective)
        flow = Flow.from_client_secrets_file(
            client_secret_path,
            scopes=effective.gmail_scopes(),
            redirect_uri=callback_url,
            autogenerate_code_verifier=False,
        )

        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        request.session["oauth_state"] = state
        if acc:
            request.session["oauth_account_id"] = acc.id
        return redirect(authorization_url)
    except Exception as e:
        logger.exception("OAuth start failed")
        q = quote(f"oauth_start_failed: {e}", safe="")
        return redirect(f"{reverse('setup')}?oauth_error={q}")


@login_required(login_url="/login")
@require_GET
def oauth_callback(request):
    logger.info("oauth_callback hit; args_keys=%s", list(request.GET.keys()))
    try:
        from core.mail_accounts import ensure_legacy_migrated, resolve_account, save_account_oauth_token

        ensure_legacy_migrated(request.user)
        account_id = request.session.get("oauth_account_id")
        acc = resolve_account(request.user, account_id)
        effective = runtime.get_effective_settings(request.user, account_id=acc.id if acc else None)
        client_secret_path = effective.GOOGLE_CLIENT_SECRET_FILE
        if not os.path.exists(client_secret_path):
            return redirect(f"{reverse('setup')}?oauth_error=client_secret_missing")

        callback_url = _oauth_callback_url(request, effective)
        flow = Flow.from_client_secrets_file(
            client_secret_path,
            scopes=effective.gmail_scopes(),
            redirect_uri=callback_url,
            autogenerate_code_verifier=False,
        )

        code = request.GET.get("code")
        if not code:
            err = (request.GET.get("error") or "missing_code").strip()
            return redirect(f"{reverse('setup')}?oauth_error={quote(err, safe='')}")

        state = request.GET.get("state")
        expected_state = request.session.get("oauth_state")
        if expected_state and state and state != expected_state:
            return redirect(f"{reverse('setup')}?oauth_error=oauth_state_mismatch")

        try:
            flow.fetch_token(code=code)
        except Exception as e:
            logger.exception("OAuth fetch_token failed")
            return HttpResponse(f"token_exchange_failed: {e}", status=200, content_type="text/plain; charset=utf-8")

        creds = flow.credentials
        token_json = creds.to_json()

        if acc:
            expected = str((acc.config_json or {}).get("GMAIL_ADDRESS") or "").strip()
            if expected:
                from googleapiclient.discovery import build

                svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
                profile = str(svc.users().getProfile(userId="me").execute().get("emailAddress") or "").strip()
                if profile.lower() != expected.lower():
                    err = (
                        f"oauth_email_mismatch: You signed in as {profile} but this mailbox "
                        f"expects {expected}. Use the correct Google account and try Connect OAuth again."
                    )
                    return redirect(f"{reverse('setup')}?oauth_error={quote(err, safe='')}&account_id={acc.id}")

            save_account_oauth_token(acc, token_json)
        else:
            from core.user_settings import save_google_token_json

            save_google_token_json(request.user, token_json)

        if "oauth_state" in request.session:
            del request.session["oauth_state"]
        aid = acc.id if acc else ""
        if "oauth_account_id" in request.session:
            del request.session["oauth_account_id"]
        return redirect(f"{reverse('setup')}?account_id={aid}" if aid else reverse("dashboard"))
    except Exception as e:
        logger.exception("OAuth callback failed")
        return HttpResponse(f"callback_error: {e}", status=200, content_type="text/plain; charset=utf-8")


@require_GET
def api_gmail_connection_status(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    from core.mail_accounts import account_to_dict, ensure_legacy_migrated, transport_summary

    ensure_legacy_migrated(request.user)
    acc = _resolve_mail_account(request)
    effective = runtime.get_effective_settings(request.user, account_id=acc.id if acc else None)
    cfg = _user_settings_dict(request)
    send_transport_ui = str(cfg.get("SEND_TRANSPORT") or effective.SEND_TRANSPORT or "")
    summary = transport_summary(request.user)
    acc_cfg = dict(acc.config_json or {}) if acc else {}
    has_client_secret = os.path.exists(effective.GOOGLE_CLIENT_SECRET_FILE)
    has_token = os.path.exists(effective.GOOGLE_TOKEN_FILE)
    has_gmail_address = bool((effective.GMAIL_ADDRESS or "").strip())

    if has_token:
        gmail_connected, token_error = gmail_oauth_try(effective)
    else:
        gmail_connected = False
        token_error = None

    imap_ok = imap_inbox_ready(effective)
    connected = _mailbox_connected_for_ui(effective, cfg, account_config=acc_cfg)
    smtp_last_ok = bool(acc_cfg.get("SMTP_LAST_TEST_OK") if acc else cfg.get("SMTP_LAST_TEST_OK"))
    out_from = (effective.outbound_from_email() or "").strip()
    gmail_poll_ready = bool(
        gmail_connected
        and (effective.GMAIL_ADDRESS or "").strip()
        and os.path.exists(effective.GOOGLE_TOKEN_FILE)
    )
    smtp_imap_poll_ready = bool(imap_ok and send_transport_ui == "smtp" and bool(out_from))
    poll_ready = bool(gmail_poll_ready or smtp_imap_poll_ready)

    accounts_payload = []
    if request.GET.get("include_accounts") == "1":
        from core.mail_accounts import list_accounts_for_user

        accounts_payload = [
            account_to_dict(a, include_kb_count=True) for a in list_accounts_for_user(request.user)
        ]

    return JsonResponse(
        {
            "ok": True,
            "connected": connected,
            "gmail_connected": gmail_connected,
            "imap_connected": imap_ok,
            "smtp_last_test_ok": smtp_last_ok,
            "send_transport": send_transport_ui,
            "active_mode": summary.get("active_mode"),
            "enabled_count": summary.get("enabled_count"),
            "account_id": acc.id if acc else None,
            "poll_ready": poll_ready,
            "has_client_secret": has_client_secret,
            "has_token": has_token,
            "has_gmail_address": has_gmail_address,
            "gmail_address": effective.GMAIL_ADDRESS,
            "token_error": token_error,
            "accounts": accounts_payload,
            "summary": summary,
        }
    )


@csrf_exempt
def api_gmail_disconnect(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        from core.mail_accounts import clear_account_oauth, ensure_legacy_migrated, resolve_account, TRANSPORT_GMAIL
        from core.user_settings import get_or_create_mail_settings, token_path_for_user

        ensure_legacy_migrated(request.user)
        body = {}
        try:
            if request.body:
                body = json.loads(request.body.decode("utf-8"))
        except Exception:
            pass
        aid = body.get("account_id") or _account_id_from_request(request)
        acc = resolve_account(request.user, aid, transport=TRANSPORT_GMAIL)
        if acc:
            clear_account_oauth(acc)
        ms = get_or_create_mail_settings(request.user)
        ms.google_oauth_token_enc = ""
        ms.save()
        token_path = token_path_for_user(request.user.id)
        if os.path.exists(token_path):
            os.remove(token_path)
        if "oauth_state" in request.session:
            del request.session["oauth_state"]
        return JsonResponse({"ok": True})
    except Exception as e:
        logger.exception("api_gmail_disconnect failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


def _processed_at_ms(processed_at: str) -> int:
    if not processed_at:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    try:
        dt = datetime.fromisoformat(str(processed_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return int(datetime.now(timezone.utc).timestamp() * 1000)


def _sort_messages_chronological(messages: list) -> list:
    return sorted(messages or [], key=lambda m: int(m.get("internal_date") or 0))


def _resolve_processed_meta(st, msg_id: str, thread_id: str | None = None) -> dict[str, Any] | None:
    """Look up ProcessedMeta by IMAP uid, imap:uid alias, or RFC Message-ID key."""
    keys: list[str] = []
    mid = str(msg_id or "").strip()
    tid = str(thread_id or "").strip()
    if mid:
        keys.append(mid)
        if mid.isdigit():
            keys.append(f"imap:{mid}")
    if tid and tid not in (mid, f"imap:{mid}"):
        keys.append(tid)
        if tid.isdigit():
            keys.append(f"imap:{tid}")
    seen: set[str] = set()
    for k in keys:
        if not k or k in seen:
            continue
        seen.add(k)
        meta = st.get_processed_meta(k)
        if meta:
            return meta
    return None


def _normalize_body_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _bodies_similar(a: str, b: str) -> bool:
    na = _normalize_body_text(a)
    nb = _normalize_body_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if shorter in longer:
        return True
    return len(shorter) >= 48 and longer.startswith(shorter[:48])


def _append_stored_app_reply(messages: list, meta: dict | None, effective: Settings) -> list:
    """Show original inbound + MailPilot auto-reply in chronological order."""
    if not meta or meta.get("action") not in ("sent", "draft"):
        return list(messages or [])
    reply_body = (meta.get("reply_body") or "").strip()
    if not reply_body:
        return list(messages or [])

    from_addr = (
        effective.outbound_from_email() or effective.SMTP_USERNAME or effective.GMAIL_ADDRESS or "You"
    ).strip()
    base_id = (messages[0].get("id") if messages else "0")
    reply_ts = _processed_at_ms(meta.get("processed_at") or "")
    reply_msg = {
        "id": f"app-reply-{base_id}",
        "from": from_addr,
        "subject": meta.get("reply_subject") or "",
        "internal_date": reply_ts or int(datetime.now(timezone.utc).timestamp() * 1000),
        "snippet": reply_body[:240],
        "body_text": reply_body,
        "is_from_me": True,
        "is_app_reply": True,
    }

    inbound_only = [m for m in (messages or []) if not m.get("is_from_me")]
    has_outbound = any(m.get("is_from_me") and (m.get("body_text") or "").strip() for m in (messages or []))

    # Inbox row can contain the auto-reply body with the customer's From (mis-threaded / quoted).
    if len(inbound_only) == 1 and _bodies_similar(inbound_only[0].get("body_text") or "", reply_body):
        original_body = (meta.get("mail_body") or "").strip()
        if not original_body:
            original_body = "(Original message text was not stored - only the auto-reply is shown below.)"
        original = {
            "id": str(inbound_only[0].get("id") or base_id),
            "from": meta.get("from_email") or inbound_only[0].get("from") or "",
            "subject": meta.get("subject") or inbound_only[0].get("subject") or "",
            "internal_date": int(inbound_only[0].get("internal_date") or 0),
            "snippet": original_body[:240],
            "body_text": original_body,
            "is_from_me": False,
        }
        if reply_ts and reply_ts <= int(original.get("internal_date") or 0):
            reply_msg["internal_date"] = int(original.get("internal_date") or 0) + 1
        return [original, reply_msg]

    if has_outbound:
        return list(messages or [])

    out = list(messages or [])
    out.append(reply_msg)
    return out


def _inbox_message_status(meta: dict[str, Any] | None) -> str | None:
    """Map processed-meta to a short UI status for the Messages list."""
    if not meta:
        return None
    action = (meta.get("action") or "").lower()
    reason = (meta.get("reason") or "").lower()
    if action == "ignored" and reason == "keyword_prefilter":
        return "reject"
    if action == "sent":
        return "sent"
    if action == "draft":
        return "draft"
    return None


def _annotate_inbox_threads(
    threads: list[dict[str, Any]], user, *, account_id: int | None = None
) -> list[dict[str, Any]]:
    st = runtime.state_store_for_user(user, account_id=account_id)
    for t in threads:
        mid = str(t.get("message_id") or "").strip()
        if not mid and t.get("thread_id") is not None:
            mid = f"imap:{t.get('thread_id')}"
        meta = st.get_processed_meta(mid) if mid else None
        status = _inbox_message_status(meta)
        if status:
            t["message_status"] = status
        else:
            t.pop("message_status", None)
    return threads


@require_GET
def api_gmail_inbox(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    from core.mail_accounts import ensure_legacy_migrated

    ensure_legacy_migrated(request.user)
    acc = _resolve_mail_account(request)
    if acc is None:
        return JsonResponse({"ok": False, "error": "no_account"}, status=400)
    effective = runtime.get_effective_settings(request.user, account_id=acc.id)
    try:
        g_ok = gmail_oauth_ready(effective) and acc.transport == "gmail_api"
        use_imap_list = acc.transport == "smtp" and (
            _smtp_imap_inbox_active(effective) or (imap_inbox_ready(effective) and not g_ok)
        )
        if use_imap_list:
            mb = ImapMailbox(settings=effective)
            threads = _annotate_inbox_threads(
                mb.list_inbox_summaries(max_threads=40), request.user, account_id=acc.id
            )
            return JsonResponse(
                {"ok": True, "threads": threads, "source": "imap", "account_id": acc.id, "email": acc.config_json.get("SMTP_USERNAME")}
            )
        if g_ok:
            from email_automation.gmail_auth import gmail_oauth_matches_configured

            matches, profile_email, configured_email = gmail_oauth_matches_configured(effective)
            if not matches:
                return JsonResponse(
                    {
                        "ok": False,
                        "error": "oauth_email_mismatch",
                        "email": configured_email or effective.GMAIL_ADDRESS,
                        "profile_email": profile_email,
                        "account_id": acc.id,
                    },
                    status=400,
                )
            client = GmailClient(settings=effective)
            threads = _annotate_inbox_threads(
                client.list_inbox_thread_summaries(max_threads=40), request.user, account_id=acc.id
            )
            return JsonResponse(
                {
                    "ok": True,
                    "threads": threads,
                    "source": "gmail",
                    "account_id": acc.id,
                    "email": effective.GMAIL_ADDRESS,
                    "profile_email": profile_email,
                    "oauth_email_mismatch": False,
                }
            )
        return JsonResponse({"ok": False, "error": "not_connected"}, status=400)
    except Exception as e:
        if is_gmail_rate_limit_error(e):
            wait = int(gmail_retry_after_seconds(e))
            return JsonResponse(
                {
                    "ok": False,
                    "error": f"Gmail rate limit - try again in about {wait} seconds.",
                    "retry_after_seconds": wait,
                },
                status=429,
            )
        logger.exception("api_gmail_inbox failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@require_GET
def api_gmail_thread_detail(request, thread_id: str):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    from core.mail_accounts import ensure_legacy_migrated

    ensure_legacy_migrated(request.user)
    acc = _resolve_mail_account(request)
    if acc is None:
        return JsonResponse({"ok": False, "error": "no_account"}, status=400)
    effective = runtime.get_effective_settings(request.user, account_id=acc.id)
    try:
        g_ok = gmail_oauth_ready(effective) and acc.transport == "gmail_api"
        uid = int(thread_id) if thread_id.isdigit() else None
        use_imap_thread = uid is not None and (
            _smtp_imap_inbox_active(effective) or (imap_inbox_ready(effective) and not g_ok)
        )
        if use_imap_thread:
            mb = ImapMailbox(settings=effective)
            data = mb.get_thread_for_ui(uid=uid)
        elif g_ok:
            from email_automation.gmail_auth import gmail_oauth_matches_configured

            if not gmail_oauth_matches_configured(effective)[0]:
                return JsonResponse({"ok": False, "error": "oauth_email_mismatch"}, status=400)
            client = GmailClient(settings=effective)
            data = client.get_thread_for_ui(thread_id)
        else:
            return JsonResponse({"ok": False, "error": "not_connected"}, status=400)
        messages = list(data.get("messages") or [])
        inbound_meta = None
        st = runtime.state_store_for_user(request.user, account_id=acc.id)
        for m in messages:
            mid = m.get("id")
            if not mid:
                continue
            meta = _resolve_processed_meta(st, str(mid), thread_id=thread_id)
            m["app_handled"] = meta is not None
            if meta:
                m["app_action"] = meta.get("action")
                m["app_reply_subject"] = meta.get("reply_subject")
                m["app_reply_body"] = meta.get("reply_body")
                m["app_processed_at"] = meta.get("processed_at")
                if not m.get("is_from_me"):
                    inbound_meta = meta
            else:
                m["app_action"] = None
                m["app_reply_subject"] = None
                m["app_reply_body"] = None
                m["app_processed_at"] = None
        if inbound_meta is None:
            inbound_meta = _resolve_processed_meta(st, thread_id, thread_id=thread_id)
        messages = _sort_messages_chronological(messages)
        messages = _append_stored_app_reply(messages, inbound_meta, effective)
        data["messages"] = messages
        return JsonResponse({"ok": True, **data})
    except Exception as e:
        if is_gmail_rate_limit_error(e):
            wait = int(gmail_retry_after_seconds(e))
            return JsonResponse(
                {
                    "ok": False,
                    "error": f"Gmail rate limit - try again in about {wait} seconds.",
                    "retry_after_seconds": wait,
                },
                status=429,
            )
        logger.exception("api_gmail_thread_detail failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@csrf_exempt
def api_trigger_poll(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

    def _run():
        ws = runtime.worker_state()
        with ws.lock:
            try:
                ws.running = True
                ws.last_error = None
                result = runtime.trigger_poll_fn(user=request.user)
                ws.last_result = {
                    "scanned": result.scanned,
                    "relevant": result.relevant,
                    "sent": result.sent,
                    "drafts": result.drafts,
                    "ignored": result.ignored,
                    "queued": result.queued,
                }
            except Exception as e:
                ws.last_error = str(e)
            finally:
                ws.last_run_at = datetime.now(timezone.utc).isoformat()
                ws.running = False

    threading.Thread(target=_run, daemon=True).start()
    return JsonResponse({"ok": True})


@require_GET
def api_kb_status(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        aid = _account_id_from_request(request)
        effective = runtime.get_effective_settings(request.user, account_id=aid)
        if not is_vector_db_configured(effective):
            return JsonResponse(
                {
                    "ok": False,
                    "configured": False,
                    "error": "No KB database connection. Set DJANGO_DB_* in .env (same DB is fine) or VECTOR_DB_DSN, and run CREATE EXTENSION vector; on that database - see docs/kb-pgvector-setup.md",
                }
            )
        vs = _get_vector_store_for_user(request.user, account_id=aid)
        st = vs.stats()
        return JsonResponse({"ok": True, "configured": True, **st})
    except Exception as e:
        return JsonResponse({"ok": False, "configured": False, "error": str(e)})


def _ingest_documents(docs: list[KBDocument], user, account_id: int | None = None) -> dict[str, Any]:
    effective = runtime.get_effective_settings(user, account_id=account_id)
    vs = _get_vector_store_for_user(user, account_id=account_id)
    total_chunks = 0
    for doc in docs:
        chunks_txt = chunk_text(doc.text)
        if not chunks_txt:
            continue
        embs = embed_texts(settings=effective, texts=chunks_txt)
        pairs = list(zip(chunks_txt, embs))
        vs.upsert_document_with_chunks(
            doc_id=doc.doc_id,
            source=doc.source,
            url=doc.url,
            title=doc.title,
            metadata=doc.metadata,
            chunks=pairs,
        )
        total_chunks += len(pairs)
    return {"documents": len(docs), "chunks": total_chunks}


def _website_crawl_path(user) -> Any:
    return user_data_dir(user.id) / "website_crawl.json"


def _set_crawl_job(user_id: int, state: dict[str, Any]) -> None:
    with _crawl_jobs_lock:
        _crawl_jobs[user_id] = state


def _patch_crawl_job(user_id: int, **updates: Any) -> None:
    with _crawl_jobs_lock:
        job = dict(_crawl_jobs.get(user_id) or {})
        if "progress" in updates and isinstance(updates["progress"], dict):
            prog = dict(job.get("progress") or {})
            prog.update(updates["progress"])
            updates = {**updates, "progress": prog}
        job.update(updates)
        _crawl_jobs[user_id] = job


def _get_crawl_job(user_id: int) -> dict[str, Any]:
    with _crawl_jobs_lock:
        return dict(_crawl_jobs.get(user_id) or {})


def _build_kb_bundle_for_user(user, account_id: int | None = None) -> dict[str, Any]:
    effective = runtime.get_effective_settings(user, account_id=account_id)
    website_crawl = load_website_crawl_file(_website_crawl_path(user))
    vector_documents: list[dict[str, Any]] = []
    if is_vector_db_configured(effective):
        vs = _get_vector_store_for_user(user, account_id=account_id)
        vector_documents = vs.export_documents(limit=200)
    return build_kb_export_bundle(
        vector_documents=vector_documents,
        website_crawl=website_crawl,
    )


@csrf_exempt
def api_kb_upload_json(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    aid = _account_id_from_request(request)
    try:
        from core.billing import can_use_kb_source

        gate = can_use_kb_source(request.user, account_id=aid)
        if not gate.allowed:
            return JsonResponse(
                {"ok": False, "error": gate.reason, "upgrade_required": True, "billing": gate.summary or {}},
                status=403,
            )
    except Exception:
        pass
    f = request.FILES.get("json_file")
    if f is None or not getattr(f, "name", ""):
        return JsonResponse({"ok": False, "error": "Missing json_file"}, status=400)
    try:
        raw = f.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Invalid JSON: {e}"}, status=400)
    try:
        docs = documents_from_json_upload(data, source_name=secure_filename(f.name))
        res = _ingest_documents(docs, request.user, account_id=aid)
        return JsonResponse({"ok": True, **res})
    except Exception as e:
        logger.exception("kb upload-json failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@csrf_exempt
def api_kb_upload_text(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    aid = _account_id_from_request(request)
    try:
        from core.billing import can_use_kb_source

        gate = can_use_kb_source(request.user, account_id=aid)
        if not gate.allowed:
            return JsonResponse(
                {"ok": False, "error": gate.reason, "upgrade_required": True, "billing": gate.summary or {}},
                status=403,
            )
    except Exception:
        pass
    f = request.FILES.get("text_file")
    if f is None or not getattr(f, "name", ""):
        return JsonResponse({"ok": False, "error": "Missing text_file"}, status=400)
    name = secure_filename(f.name) or "upload.txt"
    lower = name.lower()
    if not (lower.endswith(".txt") or lower.endswith(".text") or lower.endswith(".md")):
        return JsonResponse(
            {"ok": False, "error": "Expected a .txt, .text, or .md file"},
            status=400,
        )
    try:
        raw = f.read().decode("utf-8", errors="replace")
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Could not read file: {e}"}, status=400)
    try:
        docs = documents_from_text_upload(raw, source_name=name)
        if not docs:
            return JsonResponse({"ok": False, "error": "Text file is empty"}, status=400)
        res = _ingest_documents(docs, request.user, account_id=aid)
        return JsonResponse({"ok": True, **res})
    except Exception as e:
        logger.exception("kb upload-text failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@csrf_exempt
def api_kb_crawl(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

    body: dict[str, Any] = {}
    if request.body and "application/json" in (request.content_type or ""):
        try:
            body = json.loads(request.body.decode("utf-8")) or {}
        except Exception:
            body = {}

    start_url = (request.POST.get("start_url") or body.get("start_url") or "").strip()
    if not start_url:
        return JsonResponse({"ok": False, "error": "Missing start_url"}, status=400)

    aid = _account_id_from_request(request)
    try:
        from core.billing import can_use_kb_source

        gate = can_use_kb_source(request.user, account_id=aid)
        if not gate.allowed:
            return JsonResponse(
                {"ok": False, "error": gate.reason, "upgrade_required": True, "billing": gate.summary or {}},
                status=403,
            )
    except Exception:
        pass
    effective = runtime.get_effective_settings(request.user, account_id=aid)
    if not is_vector_db_configured(effective):
        return JsonResponse(
            {"ok": False, "error": "kb_not_configured", "configured": False},
            status=400,
        )

    user = request.user
    uid = user.id
    crawl_account_id = aid
    started_at = datetime.now(timezone.utc).isoformat()
    _set_crawl_job(
        uid,
        {
            "running": True,
            "error": None,
            "result": None,
            "start_url": start_url,
            "started_at": started_at,
            "finished_at": None,
            "progress": {
                "phase": "starting",
                "percent": 0,
                "message": "Starting crawl…",
                "pages_fetched": 0,
                "max_pages": 80,
            },
        },
    )

    def _run():
        result: dict[str, Any] | None = None
        err: str | None = None
        export_stats: dict[str, Any] = {}

        def _on_crawl_progress(data: dict[str, Any]) -> None:
            _patch_crawl_job(uid, running=True, progress=data)

        try:
            pages = crawl_site(start_url=start_url, on_progress=_on_crawl_progress)
            _patch_crawl_job(
                uid,
                running=True,
                progress={
                    "phase": "exporting",
                    "percent": 75,
                    "message": "Deduplicating and building knowledge text…",
                    "pages_fetched": len(pages),
                },
            )
            export_payload = build_website_crawl_export(pages, start_url=start_url)
            export_stats = (export_payload.get("crawl") or {}).get("stats") or {}
            save_website_crawl_file(_website_crawl_path(user), export_payload)
            _patch_crawl_job(
                uid,
                running=True,
                progress={
                    "phase": "ingesting",
                    "percent": 88,
                    "message": "Embedding into knowledge base…",
                    "pages_fetched": export_stats.get("pages_included", len(pages)),
                },
            )
            docs = documents_from_crawl_export(export_payload)
            ingest_res = _ingest_documents(docs, user, account_id=crawl_account_id)
            result = {
                **ingest_res,
                "pages_fetched": export_stats.get("pages_fetched", len(pages)),
                "pages_included": export_stats.get("pages_included", 0),
                "paragraphs_deduplicated": export_stats.get("paragraphs_deduplicated", 0),
                "knowledge_char_count": export_stats.get("knowledge_char_count", 0),
                "start_url": start_url,
            }
        except Exception as e:
            logger.exception("kb crawl failed user_id=%s", uid)
            err = str(e)
        finished_at = datetime.now(timezone.utc).isoformat()
        final_progress = (
            {
                "phase": "done",
                "percent": 100,
                "message": "Crawl complete",
                "pages_fetched": (result or {}).get("pages_included")
                or export_stats.get("pages_included", 0),
            }
            if not err
            else {
                "phase": "error",
                "percent": 0,
                "message": err,
            }
        )
        _set_crawl_job(
            uid,
            {
                "running": False,
                "error": err,
                "result": result,
                "start_url": start_url,
                "started_at": started_at,
                "finished_at": finished_at,
                "stats": export_stats,
                "progress": final_progress,
            },
        )

    threading.Thread(target=_run, daemon=True).start()
    return JsonResponse({"ok": True, "started": True, "start_url": start_url})


@require_GET
def api_kb_crawl_status(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    job = _get_crawl_job(request.user.id)
    return JsonResponse(
        {
            "ok": True,
            "running": bool(job.get("running")),
            "error": job.get("error"),
            "result": job.get("result"),
            "start_url": job.get("start_url"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "stats": job.get("stats"),
            "progress": job.get("progress"),
        }
    )


@csrf_exempt
def api_kb_clear(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        aid = _account_id_from_request(request)
        try:
            from core.billing import can_use_kb_source

            gate = can_use_kb_source(request.user, account_id=aid, replacing=True)
            if not gate.allowed:
                return JsonResponse(
                    {"ok": False, "error": gate.reason, "upgrade_required": True, "billing": gate.summary or {}},
                    status=403,
                )
        except Exception:
            pass
        effective = runtime.get_effective_settings(request.user, account_id=aid)
        crawl_deleted = delete_website_crawl_file(_website_crawl_path(request.user))
        res: dict[str, Any] = {"deleted_documents": 0, "deleted_chunks": 0}
        if is_vector_db_configured(effective):
            vs = _get_vector_store_for_user(request.user, account_id=aid)
            res = vs.clear()
        return JsonResponse({"ok": True, **res, "deleted_crawl_file": crawl_deleted})
    except Exception as e:
        logger.exception("kb clear failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@require_GET
def api_kb_export_json(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        aid = _account_id_from_request(request)
        effective = runtime.get_effective_settings(request.user, account_id=aid)
        if not is_vector_db_configured(effective):
            return JsonResponse({"ok": True, "documents": []})
        vs = _get_vector_store_for_user(request.user, account_id=aid)
        docs = vs.export_documents(limit=200)
        return JsonResponse({"ok": True, "documents": docs})
    except Exception as e:
        logger.exception("kb export failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@require_GET
def api_kb_export_bundle(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        bundle = _build_kb_bundle_for_user(request.user, account_id=_account_id_from_request(request))
        return JsonResponse({"ok": True, **bundle})
    except Exception as e:
        logger.exception("kb export-bundle failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@csrf_exempt
def api_kb_replace_json(request):
    """
    Replace (clear then ingest) KB from JSON payload.
    Body can be:
      - mailpilot_kb_bundle (website_crawl + documents)
      - {"documents": [{title,url,text,...}, ...]}
      - a list of {title,url,text}
      - any dict JSON (flattened into one document)
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    ct = request.content_type or ""
    if "application/json" not in ct:
        return JsonResponse({"ok": False, "error": "expected_json"}, status=400)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"invalid_json: {e}"}, status=400)
    try:
        aid = _account_id_from_request(request)
        effective = runtime.get_effective_settings(request.user, account_id=aid)
        if not is_vector_db_configured(effective):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "kb_not_configured",
                },
                status=400,
            )
        vs = _get_vector_store_for_user(request.user, account_id=aid)
        cleared = vs.clear()
        if is_kb_bundle(payload):
            wc = payload.get("website_crawl")
            if isinstance(wc, dict) and wc.get("knowledge"):
                save_website_crawl_file(_website_crawl_path(request.user), wc)
            docs = documents_from_kb_bundle(payload)
        else:
            docs = documents_from_json_upload(payload, source_name="kb_edit.json")
        if not docs:
            return JsonResponse({"ok": False, "error": "no_documents_to_ingest"}, status=400)
        res = _ingest_documents(docs, request.user, account_id=aid)
        return JsonResponse({"ok": True, **cleared, **res})
    except Exception as e:
        logger.exception("kb replace failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@require_GET
def api_pending(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    from core.mail_accounts import ensure_legacy_migrated

    ensure_legacy_migrated(request.user)
    acc = _resolve_mail_account(request)
    account_id = acc.id if acc else None
    st = runtime.state_store_for_user(request.user, account_id=account_id)
    effective = runtime.get_effective_settings(request.user, account_id=account_id)
    items = st.list_queue_items(limit=20)
    try:
        if os.path.exists(effective.GOOGLE_TOKEN_FILE):
            from email_automation.gmail_auth import gmail_oauth_matches_configured

            if gmail_oauth_matches_configured(effective)[0]:
                client = GmailClient(settings=effective)
                for it in items:
                    mid = it.get("message_id") or ""
                    if not mid:
                        continue
                    if (it.get("from_email") or "").strip() and (it.get("subject") or "").strip():
                        continue
                    try:
                        from_email, subject = client.get_message_from_and_subject(mid)
                        st.update_processed_details(
                            message_id=mid,
                            from_email=from_email,
                            subject=subject,
                        )
                        it["from_email"] = (it.get("from_email") or "").strip() or from_email
                        it["subject"] = (it.get("subject") or "").strip() or subject
                    except Exception:
                        pass
    except Exception:
        pass
    return JsonResponse(
        {
            "ok": True,
            "items": items,
            "account_id": account_id,
        }
    )


@csrf_exempt
def api_admin_config(request):
    if request.method == "GET":
        if not check_api_access(request):
            return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
        effective = runtime.get_effective_settings(request.user)
        return JsonResponse(
            {
                "ok": True,
                "effective": {
                    "REPLY_MODE": effective.REPLY_MODE,
                    "SEND_TRANSPORT": effective.SEND_TRANSPORT,
                    "SERVICE_KEYWORDS": effective.SERVICE_KEYWORDS,
                    "SERVICE_BRAND_TOKENS": effective.SERVICE_BRAND_TOKENS,
                    "SERVICE_SENDER_DOMAIN_ALLOWLIST": effective.SERVICE_SENDER_DOMAIN_ALLOWLIST,
                    "SERVICE_SENDER_DOMAIN_BLOCKLIST": effective.SERVICE_SENDER_DOMAIN_BLOCKLIST,
                    "RELEVANCE_THRESHOLD": effective.RELEVANCE_THRESHOLD,
                    "VECTOR_DB_DSN": "***" if (effective.VECTOR_DB_DSN or "").strip() else "",
                    "EMBEDDING_MODEL": effective.EMBEDDING_MODEL,
                    "EMBEDDING_DIM": effective.EMBEDDING_DIM,
                    "SMTP_HOST": effective.SMTP_HOST,
                    "SMTP_PORT": effective.SMTP_PORT,
                    "SMTP_USERNAME": effective.SMTP_USERNAME,
                    "SMTP_PASSWORD": "***" if effective.SMTP_PASSWORD is not None else "",
                    "SMTP_USE_TLS": effective.SMTP_USE_TLS,
                    "SMTP_USE_SSL": effective.SMTP_USE_SSL,
                    "SMTP_VERIFY_TLS": effective.SMTP_VERIFY_TLS,
                    "SMTP_TLS_SERVERNAME": effective.SMTP_TLS_SERVERNAME,
                    "SMTP_FROM_EMAIL": effective.SMTP_FROM_EMAIL,
                    "IMAP_HOST": effective.IMAP_HOST,
                    "IMAP_PORT": effective.IMAP_PORT,
                    "IMAP_USERNAME": effective.IMAP_USERNAME,
                    "IMAP_PASSWORD": "***" if effective.IMAP_PASSWORD is not None else "",
                    "IMAP_MAILBOX": effective.IMAP_MAILBOX,
                    "IMAP_VERIFY_TLS": effective.IMAP_VERIFY_TLS,
                    "IMAP_TLS_SERVERNAME": effective.IMAP_TLS_SERVERNAME,
                },
            }
        )

    if request.method == "POST":
        if not check_api_access(request):
            return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
        ct = request.content_type or ""
        if "application/json" not in ct:
            return JsonResponse({"ok": False, "error": "expected_json"}, status=400)
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        allowed = {
            "REPLY_MODE",
            "SEND_TRANSPORT",
            "SERVICE_KEYWORDS",
            "SERVICE_BRAND_TOKENS",
            "SERVICE_SENDER_DOMAIN_ALLOWLIST",
            "SERVICE_SENDER_DOMAIN_BLOCKLIST",
            "RELEVANCE_THRESHOLD",
            "VECTOR_DB_DSN",
            "EMBEDDING_MODEL",
            "EMBEDDING_DIM",
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_USE_TLS",
            "SMTP_USE_SSL",
            "SMTP_VERIFY_TLS",
            "SMTP_TLS_SERVERNAME",
            "SMTP_FROM_EMAIL",
            "IMAP_HOST",
            "IMAP_PORT",
            "IMAP_USERNAME",
            "IMAP_PASSWORD",
            "IMAP_MAILBOX",
            "IMAP_VERIFY_TLS",
            "IMAP_TLS_SERVERNAME",
        }
        patch = {k: v for k, v in payload.items() if k in allowed}

        # Setup UI expects: IMAP uses the same username/password as SMTP.
        # The client sends SMTP creds + IMAP host/port/tls settings, but not IMAP username/password.
        # If we don't derive those here, IMAP inbox never becomes "ready" -> no mailbox messages.
        smtp_host = str(patch.get("SMTP_HOST") or "").strip()
        smtp_user = str(patch.get("SMTP_USERNAME") or "").strip()
        smtp_tls_servername = str(patch.get("SMTP_TLS_SERVERNAME") or "").strip()
        imap_host = str(patch.get("IMAP_HOST") or "").strip()
        imap_user = str(patch.get("IMAP_USERNAME") or "").strip()

        if smtp_host and not imap_host:
            # smtp.<domain> -> imap.<domain>
            host_l = smtp_host.lower()
            if host_l.startswith("smtp."):
                domain = smtp_host[5:]
            else:
                # Fallback: drop the first label
                parts = smtp_host.split(".", 1)
                domain = parts[1] if len(parts) == 2 else smtp_host
            if domain:
                patch["IMAP_HOST"] = f"imap.{domain}"

        imap_tls_servername = str(patch.get("IMAP_TLS_SERVERNAME") or "").strip()
        if smtp_tls_servername and not imap_tls_servername:
            patch["IMAP_TLS_SERVERNAME"] = smtp_tls_servername

        if smtp_user and not imap_user:
            patch["IMAP_USERNAME"] = smtp_user

        # Copy SMTP password -> IMAP password when IMAP password wasn't provided.
        # (Setup UI never sends IMAP_PASSWORD.)
        smtp_password = patch.get("SMTP_PASSWORD")
        imap_password = patch.get("IMAP_PASSWORD")
        if smtp_password is not None and (imap_password is None or str(imap_password).strip() == ""):
            smtp_password_str = (
                smtp_password.get_secret_value() if hasattr(smtp_password, "get_secret_value") else str(smtp_password)
            )
            if smtp_password_str.strip():
                patch["IMAP_PASSWORD"] = smtp_password

        for _k in ("SMTP_PASSWORD", "IMAP_PASSWORD"):
            if patch.get(_k) == "":
                patch.pop(_k, None)
        from core.user_settings import save_settings_patch

        save_settings_patch(request.user, patch)
        return JsonResponse({"ok": True, "updated": sorted(patch.keys())})

    return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)


@csrf_exempt
def api_smtp_test(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        from core.mail_accounts import ensure_legacy_migrated, patch_account_config

        ensure_legacy_migrated(request.user)
        acc = _resolve_mail_account(request)
        if acc is None:
            return JsonResponse({"ok": False, "error": "no_account"}, status=400)
        effective = runtime.get_effective_settings(request.user, account_id=acc.id)
        to_email = (
            (effective.outbound_from_email() or "").strip()
            or (effective.SMTP_USERNAME or "").strip()
            or (getattr(request.user, "email", None) or "").strip()
        )
        if not to_email or "@" not in to_email:
            return JsonResponse(
                {"ok": False, "error": "Set a From address or SMTP username to receive the test email."},
                status=200,
            )
        client = SMTPClient(settings=effective)
        client.test_connection()
        client.send_test_email(to_email)
        patch_account_config(
            acc,
            {
                "SMTP_LAST_TEST_OK": True,
                "SMTP_LAST_TEST_AT": datetime.now(timezone.utc).isoformat(),
                "SMTP_LAST_TEST_ERROR": "",
            },
        )
        return JsonResponse({"ok": True, "sent_to": to_email})
    except Exception as e:
        try:
            from core.mail_accounts import ensure_legacy_migrated, patch_account_config

            ensure_legacy_migrated(request.user)
            acc = _resolve_mail_account(request)
            if acc:
                patch_account_config(
                    acc,
                    {
                        "SMTP_LAST_TEST_OK": False,
                        "SMTP_LAST_TEST_AT": datetime.now(timezone.utc).isoformat(),
                        "SMTP_LAST_TEST_ERROR": str(e),
                    },
                )
        except Exception:
            pass
        return JsonResponse({"ok": False, "error": str(e)}, status=200)


@require_GET
def api_smtp_status(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    cfg = _user_settings_dict(request)
    return JsonResponse(
        {
            "ok": True,
            "last_test_ok": bool(cfg.get("SMTP_LAST_TEST_OK")),
            "last_test_at": (cfg.get("SMTP_LAST_TEST_AT") or ""),
            "last_test_error": (cfg.get("SMTP_LAST_TEST_ERROR") or ""),
        }
    )


@csrf_exempt
def api_smtp_disconnect(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    from core.user_settings import save_settings_patch

    save_settings_patch(
        request.user,
        {
            "SEND_TRANSPORT": "gmail_api",
            "SMTP_HOST": "",
            "SMTP_PORT": 587,
            "SMTP_USERNAME": "",
            "SMTP_PASSWORD": "",
            "SMTP_USE_TLS": True,
            "SMTP_USE_SSL": False,
            "SMTP_VERIFY_TLS": True,
            "SMTP_TLS_SERVERNAME": "",
            "SMTP_FROM_EMAIL": "",
            "IMAP_HOST": "",
            "IMAP_PORT": 993,
            "IMAP_USERNAME": "",
            "IMAP_PASSWORD": "",
            "IMAP_MAILBOX": "INBOX",
            "IMAP_VERIFY_TLS": True,
            "IMAP_TLS_SERVERNAME": "",
            "SMTP_LAST_TEST_OK": False,
            "SMTP_LAST_TEST_AT": datetime.now(timezone.utc).isoformat(),
            "SMTP_LAST_TEST_ERROR": "disconnected_by_user",
        },
    )
    return JsonResponse({"ok": True})


@require_GET
def api_telegram_status(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    from core.telegram_notify import telegram_status_for_user

    try:
        from core.billing import can_use_integration

        gate = can_use_integration(request.user, "telegram")
        return JsonResponse({"ok": True, "plan_allowed": gate.allowed, **telegram_status_for_user(request.user)})
    except Exception:
        return JsonResponse({"ok": True, "plan_allowed": True, **telegram_status_for_user(request.user)})


@csrf_exempt
@ratelimit(key="user", rate="20/m", block=True)
def api_telegram_config(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        from core.billing import can_use_integration

        gate = can_use_integration(request.user, "telegram")
        if not gate.allowed:
            return JsonResponse(
                {"ok": False, "error": gate.reason, "upgrade_required": True, "billing": gate.summary or {}},
                status=403,
            )
    except Exception:
        pass
    ct = request.content_type or ""
    if "application/json" not in ct:
        return JsonResponse({"ok": False, "error": "expected_json"}, status=400)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    from core.telegram_notify import save_telegram_settings, telegram_status_for_user

    patch: dict[str, Any] = {}
    if "TELEGRAM_CHAT_ID" in payload:
        patch["TELEGRAM_CHAT_ID"] = str(payload.get("TELEGRAM_CHAT_ID") or "").strip()
    if "TELEGRAM_NOTIFY_EVENTS" in payload:
        patch["TELEGRAM_NOTIFY_EVENTS"] = str(payload.get("TELEGRAM_NOTIFY_EVENTS") or "all").strip()
    if "TELEGRAM_ENABLED" in payload:
        patch["TELEGRAM_ENABLED"] = bool(payload.get("TELEGRAM_ENABLED"))
    if "TELEGRAM_REPLY_ENABLED" in payload:
        patch["TELEGRAM_REPLY_ENABLED"] = bool(payload.get("TELEGRAM_REPLY_ENABLED"))
    if "TELEGRAM_BOT_TOKEN" in payload:
        token = str(payload.get("TELEGRAM_BOT_TOKEN") or "").strip()
        if token and token not in ("***", "••••"):
            patch["TELEGRAM_BOT_TOKEN"] = token
    save_telegram_settings(request.user, patch)
    return JsonResponse({"ok": True, **telegram_status_for_user(request.user)})


@csrf_exempt
@ratelimit(key="user", rate="10/m", block=True)
def api_telegram_test(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        from core.billing import can_use_integration

        gate = can_use_integration(request.user, "telegram")
        if not gate.allowed:
            return JsonResponse(
                {"ok": False, "error": gate.reason, "upgrade_required": True, "billing": gate.summary or {}},
                status=403,
            )
    except Exception:
        pass
    from core.telegram_notify import send_test_message

    ok, err = send_test_message(request.user)
    if not ok:
        return JsonResponse({"ok": False, "error": err or "test_failed"}, status=400)
    return JsonResponse({"ok": True, "message": "Test message sent"})


@require_GET
def api_whatsapp_status(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    from core.whatsapp_notify import whatsapp_status_for_user

    base = request.build_absolute_uri("/").rstrip("/")
    try:
        from core.billing import can_use_integration

        plan_allowed = can_use_integration(request.user, "whatsapp").allowed
    except Exception:
        plan_allowed = True
    return JsonResponse(
        {
            "ok": True,
            "plan_allowed": plan_allowed,
            **whatsapp_status_for_user(request.user),
            "webhook_url": f"{base}/api/whatsapp/webhook",
        }
    )


@csrf_exempt
@ratelimit(key="user", rate="20/m", block=True)
def api_whatsapp_config(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        from core.billing import can_use_integration

        gate = can_use_integration(request.user, "whatsapp")
        if not gate.allowed:
            return JsonResponse(
                {"ok": False, "error": gate.reason, "upgrade_required": True, "billing": gate.summary or {}},
                status=403,
            )
    except Exception:
        pass
    ct = request.content_type or ""
    if "application/json" not in ct:
        return JsonResponse({"ok": False, "error": "expected_json"}, status=400)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    from core.whatsapp_notify import save_whatsapp_settings, whatsapp_status_for_user

    patch: dict[str, Any] = {}
    for key in (
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_TO_PHONE",
        "WHATSAPP_VERIFY_TOKEN",
    ):
        if key in payload:
            patch[key] = str(payload.get(key) or "").strip()
    if "WHATSAPP_NOTIFY_EVENTS" in payload:
        patch["WHATSAPP_NOTIFY_EVENTS"] = str(payload.get("WHATSAPP_NOTIFY_EVENTS") or "all").strip()
    if "WHATSAPP_ENABLED" in payload:
        patch["WHATSAPP_ENABLED"] = bool(payload.get("WHATSAPP_ENABLED"))
    if "WHATSAPP_REPLY_ENABLED" in payload:
        patch["WHATSAPP_REPLY_ENABLED"] = bool(payload.get("WHATSAPP_REPLY_ENABLED"))
    if "WHATSAPP_ACCESS_TOKEN" in payload:
        token = str(payload.get("WHATSAPP_ACCESS_TOKEN") or "").strip()
        if token and token not in ("***", "••••"):
            patch["WHATSAPP_ACCESS_TOKEN"] = token
    save_whatsapp_settings(request.user, patch)
    base = request.build_absolute_uri("/").rstrip("/")
    return JsonResponse(
        {
            "ok": True,
            **whatsapp_status_for_user(request.user),
            "webhook_url": f"{base}/api/whatsapp/webhook",
        }
    )


@csrf_exempt
@ratelimit(key="user", rate="10/m", block=True)
def api_whatsapp_test(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        from core.billing import can_use_integration

        gate = can_use_integration(request.user, "whatsapp")
        if not gate.allowed:
            return JsonResponse(
                {"ok": False, "error": gate.reason, "upgrade_required": True, "billing": gate.summary or {}},
                status=403,
            )
    except Exception:
        pass
    from core.whatsapp_notify import send_test_message as wa_send_test

    ok, err = wa_send_test(request.user)
    if not ok:
        return JsonResponse({"ok": False, "error": err or "test_failed"}, status=400)
    return JsonResponse({"ok": True, "message": "Test message sent"})


@csrf_exempt
def api_whatsapp_webhook(request):
    """Meta WhatsApp Cloud API webhook (no session auth; verify token on GET)."""
    from django.http import HttpResponse

    from core.whatsapp_webhook import handle_webhook_verification, parse_webhook_body, process_webhook_payload

    if request.method == "GET":
        mode = request.GET.get("hub.mode") or ""
        token = request.GET.get("hub.verify_token") or ""
        challenge = request.GET.get("hub.challenge") or ""
        verified = handle_webhook_verification(mode=mode, token=token, challenge=challenge)
        if verified is None:
            return HttpResponse("Forbidden", status=403)
        return HttpResponse(verified, content_type="text/plain")

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    payload = parse_webhook_body(request.body)
    if payload:
        try:
            process_webhook_payload(payload)
        except Exception:
            logger.exception("api_whatsapp_webhook process failed")
    return JsonResponse({"ok": True})
