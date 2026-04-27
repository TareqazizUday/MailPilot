from __future__ import annotations

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from core import views as legacy_views


urlpatterns = [
    # OpenAPI schema + docs
    path("schema/", SpectacularAPIView.as_view(), name="api_schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api_schema"), name="api_docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api_schema"), name="api_redoc"),
    # Versioned API
    path("v1/", include("api.v1.urls")),
    # Legacy endpoints (keep working)
    path("setup/credentials", legacy_views.api_setup_credentials, name="api_setup_credentials_legacy"),
    path("gmail/oauth/start", legacy_views.oauth_start, name="oauth_start_legacy"),
    path("gmail/oauth/callback", legacy_views.oauth_callback, name="oauth_callback_legacy"),
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
    path("kb/crawl", legacy_views.api_kb_crawl, name="api_kb_crawl_legacy"),
    path("kb/clear", legacy_views.api_kb_clear, name="api_kb_clear_legacy"),
    path("kb/export-json", legacy_views.api_kb_export_json, name="api_kb_export_json_legacy"),
    path("kb/replace-json", legacy_views.api_kb_replace_json, name="api_kb_replace_json_legacy"),
    path("pending", legacy_views.api_pending, name="api_pending_legacy"),
    path("admin/config", legacy_views.api_admin_config, name="api_admin_config_legacy"),
    path("smtp/test", legacy_views.api_smtp_test, name="api_smtp_test_legacy"),
    path("smtp/status", legacy_views.api_smtp_status, name="api_smtp_status_legacy"),
    path("smtp/disconnect", legacy_views.api_smtp_disconnect, name="api_smtp_disconnect_legacy"),
]

