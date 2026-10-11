from __future__ import annotations

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from api.v1 import auth_api, pricing_api, views, wrappers


urlpatterns = [
    # Auth
    path("auth/token", auth_api.EmailOrUsernameTokenView.as_view(), name="v1_token_obtain_pair"),
    path("auth/refresh", TokenRefreshView.as_view(), name="v1_token_refresh"),
    path("auth/signup", auth_api.signup, name="v1_auth_signup"),
    path("auth/password-reset/request", auth_api.password_reset_request, name="v1_password_reset_request"),
    path("auth/password-reset/verify", auth_api.password_reset_verify, name="v1_password_reset_verify"),
    path("auth/password-reset/confirm", auth_api.password_reset_confirm, name="v1_password_reset_confirm"),
    path("me", auth_api.me, name="v1_me"),
    path("me/change-password", auth_api.change_password, name="v1_change_password"),
    path("me/avatar", auth_api.me_avatar, name="v1_me_avatar"),
    # Mobile OAuth helpers
    path("gmail/oauth/authorize-url", views.gmail_oauth_authorize_url, name="v1_gmail_oauth_authorize_url"),
    path("gmail/oauth/exchange", views.gmail_oauth_exchange, name="v1_gmail_oauth_exchange"),
    # Mail setup / connections
    path("setup/credentials", views.setup_credentials, name="v1_setup_credentials"),
    path("gmail/connection-status", views.gmail_connection_status, name="v1_gmail_connection_status"),
    path("gmail/disconnect", views.gmail_disconnect, name="v1_gmail_disconnect"),
    path("gmail/inbox", views.gmail_inbox, name="v1_gmail_inbox"),
    path("gmail/threads/<str:thread_id>", views.gmail_thread_detail, name="v1_gmail_thread_detail"),
    # Worker
    path("trigger-poll", views.trigger_poll, name="v1_trigger_poll"),
    path("pending", views.pending, name="v1_pending"),
    path("dashboard/summary", views.dashboard_summary, name="v1_dashboard_summary"),
    # Knowledge base
    path("kb/status", views.kb_status, name="v1_kb_status"),
    path("kb/upload-json", views.kb_upload_json, name="v1_kb_upload_json"),
    path("kb/upload-text", views.kb_upload_text, name="v1_kb_upload_text"),
    path("kb/crawl", views.kb_crawl, name="v1_kb_crawl"),
    path("kb/crawl/status", views.kb_crawl_status, name="v1_kb_crawl_status"),
    path("kb/export-bundle", views.kb_export_bundle, name="v1_kb_export_bundle"),
    path("kb/clear", views.kb_clear, name="v1_kb_clear"),
    path("kb/export-json", views.kb_export_json, name="v1_kb_export_json"),
    path("kb/replace-json", views.kb_replace_json, name="v1_kb_replace_json"),
    # Admin / config
    path("admin/config", views.admin_config, name="v1_admin_config"),
    # SMTP / IMAP
    path("smtp/test", views.smtp_test, name="v1_smtp_test"),
    path("smtp/status", views.smtp_status, name="v1_smtp_status"),
    path("smtp/disconnect", views.smtp_disconnect, name="v1_smtp_disconnect"),
    # Mail accounts (JWT wrappers)
    path("mail-accounts", wrappers.mail_accounts_list, name="v1_mail_accounts_list"),
    path("mail-accounts/create", wrappers.mail_accounts_create, name="v1_mail_accounts_create"),
    path("mail-accounts/<int:account_id>", wrappers.mail_accounts_detail, name="v1_mail_accounts_detail"),
    path("mail-accounts/<int:account_id>/test-smtp", wrappers.mail_account_test_smtp, name="v1_mail_account_test_smtp"),
    path(
        "mail-accounts/<int:account_id>/setup-credentials",
        wrappers.mail_account_setup_credentials,
        name="v1_mail_account_setup_credentials",
    ),
    path(
        "mail-accounts/<int:account_id>/disconnect-gmail",
        wrappers.mail_account_disconnect_gmail,
        name="v1_mail_account_disconnect_gmail",
    ),
    path("transport-mode", wrappers.transport_mode, name="v1_transport_mode"),
    # Billing
    path("pricing", pricing_api.pricing, name="v1_pricing"),
    path("billing/summary", wrappers.billing_summary, name="v1_billing_summary"),
    path("billing/select-plan", wrappers.billing_select_plan, name="v1_billing_select_plan"),
    # Integrations
    path("telegram/status", wrappers.telegram_status, name="v1_telegram_status"),
    path("telegram/config", wrappers.telegram_config, name="v1_telegram_config"),
    path("telegram/test", wrappers.telegram_test, name="v1_telegram_test"),
    path("whatsapp/status", wrappers.whatsapp_status, name="v1_whatsapp_status"),
    path("whatsapp/config", wrappers.whatsapp_config, name="v1_whatsapp_config"),
    path("whatsapp/test", wrappers.whatsapp_test, name="v1_whatsapp_test"),
]
