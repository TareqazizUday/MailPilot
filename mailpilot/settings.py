"""Django settings for Mailpilot — mirrors Flask `email_automation` app behavior."""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# Mailpilot project root: the folder that contains `manage.py`, `.env`, `requirements.txt`, `templates/`, `data/`.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or os.environ.get("FLASK_SECRET_KEY") or "dev-email-automation-secret"

_dbg = (os.environ.get("DJANGO_DEBUG") or os.environ.get("FLASK_DEBUG") or "true").lower()
DEBUG = _dbg in ("1", "true", "yes")

ALLOWED_HOSTS = (
    ["*"]
    if DEBUG
    else [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.RequestLogMiddleware",
]

ROOT_URLCONF = "mailpilot.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.nav_context",
            ],
        },
    },
]

WSGI_APPLICATION = "mailpilot.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "django.sqlite3",
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.db"

LOGIN_URL = "/login"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/login"

AUTH_PASSWORD_VALIDATORS: list = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# User uploads (profile avatars, etc.)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# SEO: canonical URLs and Open Graph image in production (optional).
# Example: SITE_URL=https://yourdomain.com  OG_IMAGE_URL=https://yourdomain.com/static/seo/og.png
SITE_URL = (os.environ.get("SITE_URL") or "").strip().rstrip("/")
OG_IMAGE_URL = (os.environ.get("OG_IMAGE_URL") or "").strip()

APPEND_SLASH = False

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "mailpilot-cache",
    }
}

# Celery (optional — when set, use `celery -A mailpilot worker` and `celery -A mailpilot beat`)
CELERY_BROKER_URL = (os.environ.get("CELERY_BROKER_URL") or "").strip()
CELERY_RESULT_BACKEND = (os.environ.get("CELERY_RESULT_BACKEND") or CELERY_BROKER_URL).strip()
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {}
if CELERY_BROKER_URL:
    _poll_sec = max(15, int(os.environ.get("MAIL_POLL_BEAT_SECONDS", "120") or "120"))
    CELERY_BEAT_SCHEDULE["poll-all-mail"] = {
        "task": "core.tasks.poll_all_users_mail",
        "schedule": timedelta(seconds=_poll_sec),
    }

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "").lower() in ("1", "true", "yes")
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0") or "0")
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "").lower() in (
    "1",
    "true",
    "yes",
)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
    if o.strip()
]
