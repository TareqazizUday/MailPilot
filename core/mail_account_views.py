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
    MODE_SMTP,
    TRANSPORT_GMAIL,
    TRANSPORT_SMTP,
    account_to_dict,
    active_transport_mode,
    build_effective_settings,
    clear_account_oauth,
    count_accounts,
    create_account,
    ensure_legacy_migrated,
    get_account,
    list_accounts_for_user,
    mode_for_transport,
    next_free_slot,
    patch_account_config,
    save_account_client_secret,
    set_active_transport_mode,
    transport_summary,
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


@csrf_exempt
@require_http_methods(["POST"])
def api_mail_accounts_create(request):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    body = _json_body(request)
    transport = str(body.get("transport") or TRANSPORT_GMAIL).strip()
    if transport not in (TRANSPORT_GMAIL, TRANSPORT_SMTP):
        return JsonResponse({"ok": False, "error": "invalid_transport"}, status=400)
    if count_accounts(request.user, transport) >= MAX_SLOTS_PER_TRANSPORT:
        return JsonResponse({"ok": False, "error": "max_slots_reached"}, status=400)
    try:
        from core.billing import can_enable_mailbox

        gate = can_enable_mailbox(request.user)
        if not gate.allowed:
            return JsonResponse(
                {
                    "ok": False,
                    "error": gate.reason or "plan_inbox_limit_reached",
                    "upgrade_required": True,
                    "billing": gate.summary or {},
                },
                status=403,
            )
    except Exception:
        pass
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
@require_http_methods(["PATCH", "DELETE"])
def api_mail_accounts_detail(request, account_id: int):
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
    acc = get_account(request.user, int(account_id))
    if acc is None:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

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
    if mode not in (MODE_GMAIL, MODE_SMTP):
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
    if acc is None or acc.transport != TRANSPORT_GMAIL:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)
    clear_account_oauth(acc)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_http_methods(["POST"])
def api_mail_account_setup_credentials(request, account_id: int):
    """Upload client_secret + gmail_address for a specific account, then redirect OAuth."""
    from django.shortcuts import redirect
    from django.urls import reverse
    from werkzeug.utils import secure_filename

    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)
    if not check_api_access(request):
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

    acc = get_account(request.user, int(account_id))
    if acc is None or acc.transport != TRANSPORT_GMAIL:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

    gmail_address = (request.POST.get("gmail_address") or "").strip()
    if not gmail_address:
        return JsonResponse({"ok": False, "error": "Missing gmail_address"}, status=400)

    secret_file = request.FILES.get("client_secret")
    if secret_file is None:
        return JsonResponse({"ok": False, "error": "Missing client_secret"}, status=400)

    filename = secure_filename(secret_file.name)
    if not filename.lower().endswith(".json"):
        return JsonResponse({"ok": False, "error": "client_secret must be .json"}, status=400)

    raw = b"".join(secret_file.chunks())
    save_account_client_secret(acc, raw.decode("utf-8"))
    patch_account_config(acc, {"GMAIL_ADDRESS": gmail_address})
    request.session["oauth_account_id"] = acc.id
    return redirect(reverse("oauth_start"))


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
