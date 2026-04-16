from __future__ import annotations

from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from api.v1 import views


urlpatterns = [
    # Auth
    path("auth/token", TokenObtainPairView.as_view(), name="v1_token_obtain_pair"),
    path("auth/refresh", TokenRefreshView.as_view(), name="v1_token_refresh"),
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
    # Knowledge base
    path("kb/status", views.kb_status, name="v1_kb_status"),
    path("kb/upload-json", views.kb_upload_json, name="v1_kb_upload_json"),
    path("kb/crawl", views.kb_crawl, name="v1_kb_crawl"),
    # Admin / config
    path("admin/config", views.admin_config, name="v1_admin_config"),
    # SMTP / IMAP
    path("smtp/test", views.smtp_test, name="v1_smtp_test"),
    path("smtp/status", views.smtp_status, name="v1_smtp_status"),
    path("smtp/disconnect", views.smtp_disconnect, name="v1_smtp_disconnect"),
]

