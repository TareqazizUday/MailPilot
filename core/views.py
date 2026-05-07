from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urljoin

from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods
from google_auth_oauthlib.flow import Flow
from werkzeug.utils import secure_filename

from core.access import check_api_access
from email_automation.gmail_auth import gmail_oauth_ready, gmail_oauth_try
from email_automation.gmail_client import GmailClient
from email_automation.imap_mailbox import ImapMailbox, imap_inbox_ready
from email_automation.kb.crawler import crawl_site
from email_automation.kb.embedder import embed_texts
from email_automation.kb.extract import KBDocument, chunk_text, documents_from_json_upload, html_to_text, stable_doc_id
from email_automation.kb.store import VectorStore, is_vector_db_configured
from email_automation.settings import Settings
from email_automation.smtp_client import SMTPClient

from core import runtime
from core.audit import log_audit

logger = logging.getLogger("mailpilot.views")


def _get_vector_store_for_user(user) -> VectorStore:
    effective = runtime.get_effective_settings(user)
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


def _mailbox_connected_for_ui(effective: Settings, cfg: dict[str, Any]) -> bool:
    """True if the user has a usable mailbox path for the *current* transport.

    IMAP credentials alone must not imply "connected" when SEND_TRANSPORT is still
    gmail_api (e.g. stale IMAP fields after saving SMTP once) — that broke the
    navbar showing Connected after Gmail OAuth disconnect.
    """
    transport = str(cfg.get("SEND_TRANSPORT") or effective.SEND_TRANSPORT or "").strip()
    if gmail_oauth_ready(effective):
        return True
    if transport == "smtp":
        if imap_inbox_ready(effective):
            return True
        return bool(cfg.get("SMTP_LAST_TEST_OK"))
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
    return HttpResponse(status=204)


@require_GET
def healthz(request):
    from django.conf import settings as dj_settings

    ws = runtime.worker_state()
    celery_on = bool(getattr(dj_settings, "CELERY_BROKER_URL", "") or "")
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
        }
    )


def _public_base_url(request) -> str:
    """Production site URL (SITE_URL) or fall back to this request."""
    from django.conf import settings as dj_settings

    u = (getattr(dj_settings, "SITE_URL", "") or "").strip().rstrip("/")
    if u:
        return u
    return request.build_absolute_uri("/").rstrip("/")


def _seo_landing_context(request) -> dict[str, Any]:
    """Meta tags, canonical URL, and JSON-LD for the public landing page."""
    from django.conf import settings as dj_settings

    base = _public_base_url(request)
    canonical = f"{base}/"

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
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
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
    ctx = _seo_landing_context(request)
    if request.user.is_authenticated:
        from core.user_settings import migrate_legacy_file_config_if_needed

        migrate_legacy_file_config_if_needed(request.user)
        effective = runtime.get_effective_settings(request.user)
        cfg = _user_settings_dict(request)
        ctx["connected"] = _mailbox_connected_for_ui(effective, cfg)
    return render(request, "landing.html", ctx)


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
    ctx: dict[str, Any] = {}
    if request.user.is_authenticated:
        effective = runtime.get_effective_settings(request.user)
        cfg = _user_settings_dict(request)
        ctx["connected"] = _mailbox_connected_for_ui(effective, cfg)
    return render(request, "terms.html", ctx)


@require_GET
def privacy_page(request):
    ctx: dict[str, Any] = {}
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
    ctx = _seo_landing_context(request)
    if request.user.is_authenticated:
        effective = runtime.get_effective_settings(request.user)
        cfg = _user_settings_dict(request)
        ctx["connected"] = _mailbox_connected_for_ui(effective, cfg)
    return render(request, "pricing.html", ctx)


@require_GET
def features_page(request):
    """
    Clean URL for features (no `#features` fragment).
    """
    ctx = _seo_landing_context(request)
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
    effective = runtime.get_effective_settings(request.user)
    cfg = _user_settings_dict(request)
    connected = _mailbox_connected_for_ui(effective, cfg)
    oauth_redirect_uri = _oauth_callback_url(request, effective)
    return render(
        request,
        "setup.html",
        {
            "connected": connected,
            "gmail_oauth_connected": gmail_oauth_ready(effective),
            "gmail_address": (cfg.get("GMAIL_ADDRESS") or ""),
            "oauth_error": (request.GET.get("oauth_error") or "").strip(),
            "oauth_redirect_uri": oauth_redirect_uri,
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
    return render(
        request,
        "profile.html",
        {
            "profile": prof,
            "connected": connected,
            "is_edit": (request.GET.get("edit") or "").strip() == "1",
            "avatar_url": avatar_url,
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
    save_client_secret_json(request.user, raw.decode("utf-8"))
    save_settings_patch(request.user, {"GMAIL_ADDRESS": gmail_address})
    return redirect(reverse("oauth_start"))


@login_required(login_url="/login")
@require_GET
def oauth_start(request):
    try:
        logger.info("oauth_start hit")
        effective = runtime.get_effective_settings(request.user)
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
        effective = runtime.get_effective_settings(request.user)
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
        from core.user_settings import save_google_token_json

        save_google_token_json(request.user, creds.to_json())

        if "oauth_state" in request.session:
            del request.session["oauth_state"]
        return redirect(reverse("dashboard"))
    except Exception as e:
        logger.exception("OAuth callback failed")
        return HttpResponse(f"callback_error: {e}", status=200, content_type="text/plain; charset=utf-8")


@require_GET
def api_gmail_connection_status(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    effective = runtime.get_effective_settings(request.user)
    cfg = _user_settings_dict(request)
    send_transport_ui = str(cfg.get("SEND_TRANSPORT") or effective.SEND_TRANSPORT or "")
    has_client_secret = os.path.exists(effective.GOOGLE_CLIENT_SECRET_FILE)
    has_token = os.path.exists(effective.GOOGLE_TOKEN_FILE)
    has_gmail_address = bool((effective.GMAIL_ADDRESS or "").strip())

    if has_token:
        gmail_connected, token_error = gmail_oauth_try(effective)
    else:
        gmail_connected = False
        token_error = None

    imap_ok = imap_inbox_ready(effective)
    connected = _mailbox_connected_for_ui(effective, cfg)
    smtp_last_ok = bool(cfg.get("SMTP_LAST_TEST_OK"))
    out_from = (effective.outbound_from_email() or "").strip()
    gmail_poll_ready = bool(
        gmail_connected
        and (effective.GMAIL_ADDRESS or "").strip()
        and os.path.exists(effective.GOOGLE_TOKEN_FILE)
    )
    smtp_imap_poll_ready = bool(imap_ok and send_transport_ui == "smtp" and bool(out_from))
    poll_ready = bool(gmail_poll_ready or smtp_imap_poll_ready)

    return JsonResponse(
        {
            "ok": True,
            "connected": connected,
            "gmail_connected": gmail_connected,
            "imap_connected": imap_ok,
            "smtp_last_test_ok": smtp_last_ok,
            "send_transport": send_transport_ui,
            "poll_ready": poll_ready,
            "has_client_secret": has_client_secret,
            "has_token": has_token,
            "has_gmail_address": has_gmail_address,
            "gmail_address": effective.GMAIL_ADDRESS,
            "token_error": token_error,
        }
    )


@csrf_exempt
def api_gmail_disconnect(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        from core.user_settings import get_or_create_mail_settings, token_path_for_user

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


@require_GET
def api_gmail_inbox(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    effective = runtime.get_effective_settings(request.user)
    try:
        g_ok = gmail_oauth_ready(effective)
        use_imap_list = _smtp_imap_inbox_active(effective) or (imap_inbox_ready(effective) and not g_ok)
        if use_imap_list:
            mb = ImapMailbox(settings=effective)
            threads = mb.list_inbox_summaries(max_threads=40)
            return JsonResponse({"ok": True, "threads": threads, "source": "imap"})
        if g_ok:
            client = GmailClient(settings=effective)
            threads = client.list_inbox_thread_summaries(max_threads=40)
            return JsonResponse({"ok": True, "threads": threads, "source": "gmail"})
        return JsonResponse({"ok": False, "error": "not_connected"}, status=400)
    except Exception as e:
        logger.exception("api_gmail_inbox failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@require_GET
def api_gmail_thread_detail(request, thread_id: str):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    effective = runtime.get_effective_settings(request.user)
    try:
        g_ok = gmail_oauth_ready(effective)
        uid = int(thread_id) if thread_id.isdigit() else None
        use_imap_thread = uid is not None and (
            _smtp_imap_inbox_active(effective) or (imap_inbox_ready(effective) and not g_ok)
        )
        if use_imap_thread:
            mb = ImapMailbox(settings=effective)
            data = mb.get_thread_for_ui(uid=uid)
        elif g_ok:
            client = GmailClient(settings=effective)
            data = client.get_thread_for_ui(thread_id)
        else:
            return JsonResponse({"ok": False, "error": "not_connected"}, status=400)
        for m in data.get("messages") or []:
            mid = m.get("id")
            if not mid:
                continue
            meta = runtime.state_store_for_user(request.user).get_processed_meta(str(mid))
            m["app_handled"] = meta is not None
            if meta:
                m["app_action"] = meta.get("action")
                m["app_reply_subject"] = meta.get("reply_subject")
                m["app_processed_at"] = meta.get("processed_at")
            else:
                m["app_action"] = None
                m["app_reply_subject"] = None
                m["app_processed_at"] = None
        return JsonResponse({"ok": True, **data})
    except Exception as e:
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
        effective = runtime.get_effective_settings(request.user)
        if not is_vector_db_configured(effective):
            return JsonResponse(
                {
                    "ok": False,
                    "configured": False,
                    "error": "No KB database connection. Set DJANGO_DB_* in .env (same DB is fine) or VECTOR_DB_DSN, and run CREATE EXTENSION vector; on that database — see docs/kb-pgvector-setup.md",
                }
            )
        vs = _get_vector_store_for_user(request.user)
        st = vs.stats()
        return JsonResponse({"ok": True, "configured": True, **st})
    except Exception as e:
        return JsonResponse({"ok": False, "configured": False, "error": str(e)})


def _ingest_documents(docs: list[KBDocument], user) -> dict[str, Any]:
    effective = runtime.get_effective_settings(user)
    vs = _get_vector_store_for_user(user)
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


@csrf_exempt
def api_kb_upload_json(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
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
        res = _ingest_documents(docs, request.user)
        return JsonResponse({"ok": True, **res})
    except Exception as e:
        logger.exception("kb upload-json failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@csrf_exempt
def api_kb_crawl(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

    start_url = (request.POST.get("start_url") or "").strip()
    if not start_url and request.body and "application/json" in (request.content_type or ""):
        try:
            body = json.loads(request.body.decode("utf-8"))
            start_url = (body.get("start_url") or "").strip()
        except Exception:
            pass
    if not start_url:
        return JsonResponse({"ok": False, "error": "Missing start_url"}, status=400)

    job_state = {"running": True, "error": None, "result": None}
    uid = request.user

    def _run():
        try:
            pages = crawl_site(start_url=start_url, max_pages=40, max_depth=2)
            docs: list[KBDocument] = []
            for p in pages:
                text, title = html_to_text(p.html)
                if not text:
                    continue
                doc_id = stable_doc_id(source="website", url=p.url, title=title or p.url, text=text)
                docs.append(
                    KBDocument(
                        doc_id=doc_id,
                        source="website",
                        url=p.url,
                        title=title or p.url,
                        text=text,
                        metadata={"fetched_at": p.fetched_at, "start_url": start_url},
                    )
                )
            res = _ingest_documents(docs, uid)
            job_state["result"] = res
        except Exception as e:
            job_state["error"] = str(e)
        finally:
            job_state["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return JsonResponse({"ok": True, "started": True})


@csrf_exempt
def api_kb_clear(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        effective = runtime.get_effective_settings(request.user)
        if not is_vector_db_configured(effective):
            return JsonResponse({"ok": True, "deleted_documents": 0, "deleted_chunks": 0})
        vs = _get_vector_store_for_user(request.user)
        res = vs.clear()
        return JsonResponse({"ok": True, **res})
    except Exception as e:
        logger.exception("kb clear failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@require_GET
def api_kb_export_json(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    try:
        effective = runtime.get_effective_settings(request.user)
        if not is_vector_db_configured(effective):
            return JsonResponse({"ok": True, "documents": []})
        vs = _get_vector_store_for_user(request.user)
        docs = vs.export_documents(limit=200)
        return JsonResponse({"ok": True, "documents": docs})
    except Exception as e:
        logger.exception("kb export failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@csrf_exempt
def api_kb_replace_json(request):
    """
    Replace (clear then ingest) KB from JSON payload.
    Body can be:
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
        effective = runtime.get_effective_settings(request.user)
        if not is_vector_db_configured(effective):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "kb_not_configured",
                },
                status=400,
            )
        vs = _get_vector_store_for_user(request.user)
        cleared = vs.clear()
        docs = documents_from_json_upload(payload, source_name="kb_edit.json")
        res = _ingest_documents(docs, request.user)
        return JsonResponse({"ok": True, **cleared, **res})
    except Exception as e:
        logger.exception("kb replace failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@require_GET
def api_pending(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    effective = runtime.get_effective_settings(request.user)
    items = runtime.state_store_for_user(request.user).list_queue_items(limit=10)
    try:
        if os.path.exists(effective.GOOGLE_TOKEN_FILE):
            client = GmailClient(settings=effective)
            for it in items:
                if (it.get("status") or "") != "completed":
                    continue
                mid = it.get("message_id") or ""
                if not mid:
                    continue
                if (it.get("from_email") or "").strip() and (it.get("subject") or "").strip():
                    continue
                try:
                    from_email, subject = client.get_message_from_and_subject(mid)
                    runtime.state_store_for_user(request.user).update_processed_details(
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
    return JsonResponse({"ok": True, "items": items})


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
        from core.user_settings import save_settings_patch

        effective = runtime.get_effective_settings(request.user)
        SMTPClient(settings=effective).test_connection()
        save_settings_patch(
            request.user,
            {
                "SMTP_LAST_TEST_OK": True,
                "SMTP_LAST_TEST_AT": datetime.now(timezone.utc).isoformat(),
                "SMTP_LAST_TEST_ERROR": "",
            },
        )
        return JsonResponse({"ok": True})
    except Exception as e:
        try:
            from core.user_settings import save_settings_patch

            save_settings_patch(
                request.user,
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
