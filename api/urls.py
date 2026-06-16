from __future__ import annotations

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from core import mail_account_views as ma_views
from core import views as legacy_views


urlpatterns = [
    # OpenAPI schema + docs
    path("schema/", SpectacularAPIView.as_view(), name="api_schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api_schema"), name="api_docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api_schema"), name="api_redoc"),
    # Versioned API
    path("v1/", include("api.v1.urls")),
    # Legacy endpoints (keep working)
    path("mail-accounts/", ma_views.api_mail_accounts_list, name="api_mail_accounts_list"),
    path("mail-accounts/create", ma_views.api_mail_accounts_create, name="api_mail_accounts_create"),
    path("mail-accounts/<int:account_id>/", ma_views.api_mail_accounts_detail, name="api_mail_accounts_detail"),
    path("mail-accounts/<int:account_id>/test-smtp", ma_views.api_mail_account_test_smtp, name="api_mail_account_test_smtp"),
    path("mail-accounts/<int:account_id>/disconnect-gmail", ma_views.api_mail_account_disconnect_gmail, name="api_mail_account_disconnect_gmail"),
    path(
        "mail-accounts/<int:account_id>/setup-credentials",
        ma_views.api_mail_account_setup_credentials,
        name="api_mail_account_setup_credentials",
    ),
    path("transport-mode/", ma_views.api_transport_mode, name="api_transport_mode"),
    path("setup/credentials", legacy_views.api_setup_credentials, name="api_setup_credentials"),
    path("gmail/oauth/start", legacy_views.oauth_start, name="oauth_start"),
    path("gmail/oauth/callback", legacy_views.oauth_callback, name="oauth_callback"),
    path("gmail/connection-status", legacy_views.api_gmail_connection_status, name="api_gmail_connection_status_legacy"),
    path("gmail/disconnect", legacy_views.api_gmail_disconnect, name="api_gmail_disconnect_legacy"),
    path("gmail/inbox", legacy_views.api_gmail_inbox, name="api_gmail_inbox_legacy"),
    path(
        "gmail/threads/<str:thread_id>",
        legacy_views.api_gmail_thread_detail,
        name="api_gmail_thread_detail_legacy",
    ),
    path("trigger-poll", legacy_views.api_trigger_poll, name="api_trigger_poll_legacy"),
    path("kb/status", legacy_views.api_kb_status, name="api_kb_status_legacy"),
    path("kb/upload-json", legacy_views.api_kb_upload_json, name="api_kb_upload_json_legacy"),
    path("kb/upload-text", legacy_views.api_kb_upload_text, name="api_kb_upload_text_legacy"),
    path("kb/crawl", legacy_views.api_kb_crawl, name="api_kb_crawl_legacy"),
    path("kb/crawl/status", legacy_views.api_kb_crawl_status, name="api_kb_crawl_status_legacy"),
    path("kb/clear", legacy_views.api_kb_clear, name="api_kb_clear_legacy"),
    path("kb/export-json", legacy_views.api_kb_export_json, name="api_kb_export_json_legacy"),
    path("kb/export-bundle", legacy_views.api_kb_export_bundle, name="api_kb_export_bundle_legacy"),
    path("kb/replace-json", legacy_views.api_kb_replace_json, name="api_kb_replace_json_legacy"),
    path("pending", legacy_views.api_pending, name="api_pending_legacy"),
    path("billing/summary", legacy_views.api_billing_summary, name="api_billing_summary_legacy"),
    path("billing/select-plan", legacy_views.api_billing_select_plan, name="api_billing_select_plan_legacy"),
    path("billing/custom-config", legacy_views.api_billing_custom_config, name="api_billing_custom_config_legacy"),
    path("billing/custom-quote", legacy_views.api_billing_custom_quote, name="api_billing_custom_quote_legacy"),
    path("admin/config", legacy_views.api_admin_config, name="api_admin_config_legacy"),
    path("smtp/test", legacy_views.api_smtp_test, name="api_smtp_test_legacy"),
    path("smtp/status", legacy_views.api_smtp_status, name="api_smtp_status_legacy"),
    path("smtp/disconnect", legacy_views.api_smtp_disconnect, name="api_smtp_disconnect_legacy"),
    path("telegram/status", legacy_views.api_telegram_status, name="api_telegram_status_legacy"),
    path("telegram/config", legacy_views.api_telegram_config, name="api_telegram_config_legacy"),
    path("telegram/test", legacy_views.api_telegram_test, name="api_telegram_test_legacy"),
    path("whatsapp/status", legacy_views.api_whatsapp_status, name="api_whatsapp_status_legacy"),
    path("whatsapp/config", legacy_views.api_whatsapp_config, name="api_whatsapp_config_legacy"),
    path("whatsapp/test", legacy_views.api_whatsapp_test, name="api_whatsapp_test_legacy"),
    path("whatsapp/webhook", legacy_views.api_whatsapp_webhook, name="api_whatsapp_webhook_legacy"),
]

