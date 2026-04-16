from __future__ import annotations

from django.contrib import admin
from django.conf import settings
from django.contrib.staticfiles import views as staticfiles_views
from django.urls import include, path
from django.views.static import serve as media_serve

urlpatterns = [
    path("api/", include("api.urls")),
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]

handler500 = "core.views.server_error"

# Serve user uploads in development/local runs even when DEBUG=False.
# In production, serve MEDIA_URL via your web server/CDN.
urlpatterns += [
    path("media/<path:path>", media_serve, {"document_root": settings.MEDIA_ROOT}),
]

# Serve STATIC_URL in development/local runs even when DEBUG=False.
# In production, serve STATIC_URL via your web server/CDN.
urlpatterns += [
    path("static/<path:path>", staticfiles_views.serve, {"insecure": True}),
]
