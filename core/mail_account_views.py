"""REST-style JSON APIs for multi-mailbox MailAccount management."""
from __future__ import annotations

import json
import os
from typing import Any

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from core.access import check_api_access
from core.mail_accounts import (
    MAX_SLOTS_PER_TRANSPORT,
    MODE_GMAIL,
    MODE_MICROSOFT,
    MODE_SMTP,
    TRANSPORT_GMAIL,
    TRANSPORT_MICROSOFT,
    TRANSPORT_SMTP,
    VALID_MODES,
    VALID_TRANSPORTS,
    account_to_dict,
    active_transport_mode,
    build_effective_settings,
    clear_account_oauth,
    count_accounts,
    create_account,
    ensure_legacy_migrated,
    get_account,
    has_shared_gmail_oauth_client,
    list_accounts_for_user,
    mode_for_transport,
    next_free_slot,
    patch_account_config,
    save_account_client_secret,
    set_active_transport_mode,
    transport_summary,
    update_shared_gmail_client_secret_value,
)
from email_automation.smtp_client import SMTPClient


def _json_body(request) -> dict[str, Any]:
    try:
        if request.body:
            return json.loads(request.body.decode("utf-8"))
        return {}
    except Exception:
        return {}


@require_GET
def api_mail_accounts_list(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    ensure_legacy_migrated(request.user)
    transport = (request.GET.get("transport") or "").strip()
    qs = list_accounts_for_user(request.user, transport=transport or None)
    accounts = [account_to_dict(a, include_kb_count=True) for a in qs]
    summary = transport_summary(request.user)
    return JsonResponse({"ok": True, "accounts": accounts, "summary": summary})


def mailbox_plan_gate_response(user) -> JsonResponse | None:
    """403 `upgrade_required` response when the plan does not allow another active mailbox."""
    try:
        from core.billing import can_enable_mailbox

        gate = can_enable_mailbox(user)
    except Exception:
        return None
    if gate.allowed:
        return None
    return JsonResponse(
        {
            "ok": False,
            "error": gate.reason or "plan_inbox_limit_reached",
            "upgrade_required": True,
            "billing": gate.summary or {},
        },
        status=403,
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_mail_accounts_create(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    body = _json_body(request)
    transport = str(body.get("transport") or TRANSPORT_GMAIL).strip()
    if transport not in VALID_TRANSPORTS:
        return JsonResponse({"ok": False, "error": "invalid_transport"}, status=400)
    if count_accounts(request.user, transport) >= MAX_SLOTS_PER_TRANSPORT:
        return JsonResponse({"ok": False, "error": "max_slots_reached"}, status=400)
    blocked = mailbox_plan_gate_response(request.user)
    if blocked is not None:
        return blocked
    try:
        acc = create_account(
            request.user,
            transport=transport,
            label=str(body.get("label") or "").strip(),
            gmail_address=str(body.get("gmail_address") or "").strip(),
        )
        return JsonResponse({"ok": True, "account": account_to_dict(acc, include_kb_count=True)})
    except ValueError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
def api_mail_accounts_detail(request, account_id: int):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    acc = get_account(request.user, int(account_id))
    if acc is None:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

    if request.method == "GET":
        return JsonResponse({"ok": True, "account": account_to_dict(acc, include_kb_count=True)})

    if request.method == "DELETE":
        acc.delete()
        return JsonResponse({"ok": True})

    body = _json_body(request)
    if "is_enabled" in body:
        want_on = bool(body["is_enabled"])
        if want_on and not acc.is_enabled:
            from core.mail_accounts import can_enable_more

            if not can_enable_more(request.user, acc.transport, excluding_account_id=acc.id):
                try:
                    from core.billing import usage_summary

                    billing = usage_summary(request.user)
                except Exception:
                    billing = {}
                return JsonResponse(
                    {
                        "ok": False,
                        "error": "plan_inbox_limit_reached",
                        "upgrade_required": True,
                        "billing": billing,
                    },
                    status=400,
                )
        acc.is_enabled = want_on
    if "label" in body:
        acc.label = str(body["label"] or "").strip()[:80]
    acc.save()

    allowed = {
        "GMAIL_ADDRESS",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_USE_TLS",
        "SMTP_USE_SSL",
        "SMTP_VERIFY_TLS",
        "SMTP_TLS_SERVERNAME",
        "SMTP_FROM_EMAIL",
        "IMAP_HOST",
        "IMAP_PORT",
        "IMAP_USERNAME",
        "IMAP_MAILBOX",
        "IMAP_VERIFY_TLS",
        "IMAP_TLS_SERVERNAME",
        "SMTP_LAST_TEST_OK",
        "SMTP_LAST_TEST_AT",
        "SMTP_LAST_TEST_ERROR",
        "PROVIDER_PROFILE",
    }
    patch = {k: v for k, v in body.items() if k in allowed or k in ("SMTP_PASSWORD", "IMAP_PASSWORD")}
    if patch:
        smtp_host = str(patch.get("SMTP_HOST") or "").strip()
        smtp_user = str(patch.get("SMTP_USERNAME") or "").strip()
        imap_host = str(patch.get("IMAP_HOST") or "").strip()
        if smtp_host and not imap_host:
            host_l = smtp_host.lower()
            domain = smtp_host[5:] if host_l.startswith("smtp.") else (smtp_host.split(".", 1)[1] if "." in smtp_host else smtp_host)
            if domain:
                patch["IMAP_HOST"] = f"imap.{domain}"
        if smtp_user and not str(patch.get("IMAP_USERNAME") or "").strip():
            patch["IMAP_USERNAME"] = smtp_user
        smtp_pw = patch.get("SMTP_PASSWORD")
        smtp_pw_str = (
            smtp_pw.get_secret_value() if hasattr(smtp_pw, "get_secret_value") else str(smtp_pw or "")
        ).strip() if smtp_pw is not None else ""
        if smtp_pw_str and "IMAP_PASSWORD" not in patch:
            patch["IMAP_PASSWORD"] = patch["SMTP_PASSWORD"]
        patch_account_config(acc, patch)
        acc.refresh_from_db()

    return JsonResponse({"ok": True, "account": account_to_dict(acc, include_kb_count=True)})


@csrf_exempt
@require_http_methods(["POST"])
def api_transport_mode(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    body = _json_body(request)
    mode = str(body.get("mode") or "").strip()
    if mode not in VALID_MODES:
        return JsonResponse({"ok": False, "error": "invalid_mode"}, status=400)
    set_active_transport_mode(request.user, mode)
    return JsonResponse({"ok": True, "summary": transport_summary(request.user)})


@csrf_exempt
@require_http_methods(["POST"])
def api_mail_account_test_smtp(request, account_id: int):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    acc = get_account(request.user, int(account_id))
    if acc is None or acc.transport != TRANSPORT_SMTP:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)
    from datetime import datetime, timezone

    effective = build_effective_settings(request.user, account_id=acc.id)
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
    try:
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
        patch_account_config(
            acc,
            {
                "SMTP_LAST_TEST_OK": False,
                "SMTP_LAST_TEST_AT": datetime.now(timezone.utc).isoformat(),
                "SMTP_LAST_TEST_ERROR": str(e),
            },
        )
        return JsonResponse({"ok": False, "error": str(e)}, status=200)


@csrf_exempt
@require_http_methods(["POST"])
def api_mail_account_disconnect_gmail(request, account_id: int):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    acc = get_account(request.user, int(account_id))
    if acc is None or acc.transport not in (TRANSPORT_GMAIL, TRANSPORT_MICROSOFT):
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)
    clear_account_oauth(acc)
    return JsonResponse({"ok": True})


def read_gmail_credentials_upload(request) -> tuple[str, str, str]:
    """Validate multipart upload. ``client_secret`` optional when shared app client exists.

    Returns (address, secret_json, error). Empty secret_json means use shared client.
    """
    from werkzeug.utils import secure_filename

    gmail_address = (request.POST.get("gmail_address") or "").strip()
    secret_file = request.FILES.get("client_secret")
    has_file = secret_file is not None and bool(getattr(secret_file, "name", ""))
    if has_file:
        if not secure_filename(secret_file.name).lower().endswith(".json"):
            return "", "", "client_secret must be .json"
        try:
            secret_json = b"".join(secret_file.chunks()).decode("utf-8")
            parsed = json.loads(secret_json)
        except (UnicodeDecodeError, ValueError):
            return "", "", "client_secret is not valid JSON"
        if not isinstance(parsed, dict) or not ({"installed", "web"} & set(parsed)):
            return "", "", "client_secret must be a Google OAuth client JSON (installed or web)"
        if gmail_address and "@" not in gmail_address:
            return "", "", "Missing gmail_address"
        return gmail_address, secret_json, ""
    if has_shared_gmail_oauth_client():
        # One-click path: address optional (filled from Google profile after consent).
        return gmail_address, "", ""
    if not gmail_address or "@" not in gmail_address:
        return "", "", "Missing gmail_address"
    return "", "", "Missing client_secret"


def _save_mailbox_gmail_credentials(request, account_id: int):
    """Returns (account, error_response)."""
    if request.method != "POST":
        return None, JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return None, JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    acc = get_account(request.user, int(account_id))
    if acc is None or acc.transport != TRANSPORT_GMAIL:
        return None, JsonResponse({"ok": False, "error": "not_found"}, status=404)
    gmail_address, secret_json, err = read_gmail_credentials_upload(request)
    if err:
        return None, JsonResponse({"ok": False, "error": err}, status=400)
    if secret_json:
        save_account_client_secret(acc, secret_json)
    if gmail_address:
        patch_account_config(acc, {"GMAIL_ADDRESS": gmail_address})
    acc.refresh_from_db()
    return acc, None


@csrf_exempt
@require_http_methods(["POST", "GET"])
def api_mail_account_connect_oauth(request, account_id: int):
    """One-click OAuth start (shared Google client or Microsoft Graph). Redirects to provider."""
    from django.shortcuts import redirect
    from django.urls import reverse

    from core.views import setup_error_redirect

    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    acc = get_account(request.user, int(account_id))
    if acc is None:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

    if acc.transport == TRANSPORT_GMAIL:
        if not has_shared_gmail_oauth_client() and not acc.client_secret_enc:
            return setup_error_redirect(request, "client_secret_missing", acc.id)
        body = _json_body(request) if request.method == "POST" else {}
        addr = str(body.get("gmail_address") or request.POST.get("gmail_address") or "").strip()
        if addr and "@" in addr:
            patch_account_config(acc, {"GMAIL_ADDRESS": addr})
        request.session["oauth_account_id"] = acc.id
        return redirect(reverse("oauth_start"))

    if acc.transport == TRANSPORT_MICROSOFT:
        from core import microsoft_oauth

        if not microsoft_oauth.is_configured():
            return setup_error_redirect(request, "microsoft_oauth_not_configured", acc.id)
        try:
            url = microsoft_oauth.start_authorization(
                request, user_id=request.user.id, account_id=acc.id
            )
        except Exception as e:
            return setup_error_redirect(request, f"microsoft_oauth_start_failed: {e}", acc.id)
        return redirect(url)

    return JsonResponse({"ok": False, "error": "unsupported_transport"}, status=400)


def _can_update_shared_gmail_secret(request) -> bool:
    """Only Django staff/superuser may rotate the server shared Google client secret.

    End users must never see or set GOCSPX — that is MailPilot app config, not mailbox connect.
    Optional escape hatch: ``MAILPILOT_ALLOW_SHARED_SECRET_UPDATE=1`` still requires staff.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))


@csrf_exempt
@require_http_methods(["POST"])
def api_update_shared_gmail_client_secret(request):
    """Rotate GOCSPX inside server shared client_secret.json (fixes invalid_client)."""
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    if not _can_update_shared_gmail_secret(request):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    body = _json_body(request)
    secret = str(
        body.get("client_secret")
        or body.get("secret")
        or request.POST.get("client_secret")
        or ""
    ).strip()
    ok, err = update_shared_gmail_client_secret_value(secret)
    if not ok:
        return JsonResponse({"ok": False, "error": err or "update_failed"}, status=400)
    return JsonResponse({"ok": True, "shared_gmail_oauth": has_shared_gmail_oauth_client()})


@csrf_exempt
@require_http_methods(["POST"])
def api_mail_account_setup_credentials(request, account_id: int):
    """Upload client_secret + gmail_address for a specific account, then redirect OAuth."""
    from django.shortcuts import redirect
    from django.urls import reverse

    from core.views import setup_error_redirect_from_json

    acc, err = _save_mailbox_gmail_credentials(request, account_id)
    if err is not None:
        return setup_error_redirect_from_json(request, err, int(account_id))
    request.session["oauth_account_id"] = acc.id
    return redirect(reverse("oauth_start"))


@csrf_exempt
@require_http_methods(["POST"])
def api_mail_account_setup_credentials_json(request, account_id: int):
    """Same upload for API clients: JSON response, OAuth is started separately."""
    acc, err = _save_mailbox_gmail_credentials(request, account_id)
    if err is not None:
        return err
    return JsonResponse({"ok": True, "account": account_to_dict(acc)})


def parse_account_id_from_request(request) -> int | None:
    raw = (
        request.GET.get("account_id")
        or request.POST.get("account_id")
        or ""
    ).strip()
    if not raw and request.body and "application/json" in (request.content_type or ""):
        try:
            body = json.loads(request.body.decode("utf-8"))
            raw = str(body.get("account_id") or "").strip()
        except Exception:
            pass
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
