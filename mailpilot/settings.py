from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# Mailpilot project root: the folder that contains `manage.py`, `.env`, `requirements.txt`, `templates/`, `data/`.
BASE_DIR = Path(__file__).resolve().parent.parent

# `.env` should win over inherited shell/system vars (e.g. stale DJANGO_DB_PORT on Windows).
load_dotenv(BASE_DIR / ".env", override=True)

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
    "core.apps.CoreConfig",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "api.apps.ApiConfig",
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

_db_engine = (os.environ.get("DJANGO_DB_ENGINE") or "django.db.backends.postgresql").strip()
_db_name = (os.environ.get("DJANGO_DB_NAME") or "mailpilot").strip()
_db_user = (os.environ.get("DJANGO_DB_USER") or "mailpilot_user").strip()
_db_password = os.environ.get("DJANGO_DB_PASSWORD") or ""
_db_host = (os.environ.get("DJANGO_DB_HOST") or "127.0.0.1").strip()
_db_port = str(os.environ.get("DJANGO_DB_PORT") or "5432").strip()

DATABASES = {
    "default": {
        "ENGINE": _db_engine,
        "NAME": _db_name,
        "USER": _db_user,
        "PASSWORD": _db_password,
        "HOST": _db_host,
        "PORT": _db_port,
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


def _load_app_config_json() -> dict:
    p = BASE_DIR / "data" / "app_config.json"
    try:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


_APP_CFG = _load_app_config_json()


def _smtp_from_django_env() -> dict | None:
    host = (os.environ.get("DJANGO_EMAIL_HOST") or "").strip()
    user = (os.environ.get("DJANGO_EMAIL_HOST_USER") or "").strip()
    pw = (os.environ.get("DJANGO_EMAIL_HOST_PASSWORD") or "").strip()
    if not (host and user and pw):
        return None
    return {
        "host": host,
        "port": int(os.environ.get("DJANGO_EMAIL_PORT", "587") or "587"),
        "user": user,
        "password": pw,
        "use_tls": (os.environ.get("DJANGO_EMAIL_USE_TLS", "true") or "true").lower()
        in ("1", "true", "yes"),
        "use_ssl": (os.environ.get("DJANGO_EMAIL_USE_SSL") or "").lower() in ("1", "true", "yes"),
        "from_addr": (os.environ.get("DJANGO_DEFAULT_FROM_EMAIL") or "").strip(),
        "verify_tls": (os.environ.get("DJANGO_EMAIL_VERIFY_TLS", "true") or "true").lower()
        in ("1", "true", "yes"),
    }


def _smtp_from_mail_env() -> dict | None:
    """Same SMTP_* keys as `.env` / email_automation (not DJANGO_EMAIL_*)."""
    host = (os.environ.get("SMTP_HOST") or "").strip()
    user = (os.environ.get("SMTP_USERNAME") or "").strip()
    pw = (os.environ.get("SMTP_PASSWORD") or "").strip()
    if not (host and user and pw):
        return None
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587") or "587"),
        "user": user,
        "password": pw,
        "use_tls": (os.environ.get("SMTP_USE_TLS", "true") or "true").lower()
        in ("1", "true", "yes"),
        "use_ssl": (os.environ.get("SMTP_USE_SSL") or "").lower() in ("1", "true", "yes"),
        "from_addr": (os.environ.get("SMTP_FROM_EMAIL") or "").strip(),
        "verify_tls": (os.environ.get("SMTP_VERIFY_TLS", "true") or "true").lower() in ("1", "true", "yes"),
        "tls_servername": (os.environ.get("SMTP_TLS_SERVERNAME") or "").strip(),
    }


def _smtp_from_app_config(cfg: dict) -> dict | None:
    host = str(cfg.get("SMTP_HOST") or "").strip()
    user = str(cfg.get("SMTP_USERNAME") or "").strip()
    pw = str(cfg.get("SMTP_PASSWORD") or "").strip()
    if not (host and user and pw):
        return None
    return {
        "host": host,
        "port": int(cfg.get("SMTP_PORT") or 587),
        "user": user,
        "password": pw,
        "use_tls": bool(cfg.get("SMTP_USE_TLS", True)),
        "use_ssl": bool(cfg.get("SMTP_USE_SSL", False)),
        "from_addr": str(cfg.get("SMTP_FROM_EMAIL") or "").strip(),
        "verify_tls": bool(cfg.get("SMTP_VERIFY_TLS", True)),
        "tls_servername": str(cfg.get("SMTP_TLS_SERVERNAME") or "").strip(),
    }


# Outbound email (password reset, etc.).
# Priority: 1) DJANGO_EMAIL_*  2) SMTP_* in `.env` (same as automation)  3) data/app_config.json
# 4) DJANGO_EMAIL_BACKEND or console.
_default_from = (os.environ.get("DJANGO_DEFAULT_FROM_EMAIL") or "").strip()
DEFAULT_FROM_EMAIL = _default_from or "MailPilot <noreply@localhost>"
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_TIMEOUT = 25
CONTACT_TEAM_EMAIL = (os.environ.get("CONTACT_TEAM_EMAIL") or "team@timerni.co.uk").strip()

_SMTP = _smtp_from_django_env() or _smtp_from_mail_env() or _smtp_from_app_config(_APP_CFG)
if _SMTP:
    _verify_tls = bool(_SMTP.get("verify_tls", True))
    _tls_servername = str(_SMTP.get("tls_servername") or "").strip()
    if not _verify_tls:
        EMAIL_BACKEND = "mailpilot.email_backend.InsecureTLSEmailBackend"
    elif _tls_servername:
        EMAIL_BACKEND = "mailpilot.email_backend.NoHostnameCheckEmailBackend"
    else:
        EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = _SMTP["host"]
    EMAIL_PORT = _SMTP["port"]
    EMAIL_HOST_USER = _SMTP["user"]
    EMAIL_HOST_PASSWORD = _SMTP["password"]
    EMAIL_USE_TLS = _SMTP["use_tls"]
    EMAIL_USE_SSL = _SMTP["use_ssl"]
    if not _default_from:
        _addr = _SMTP.get("from_addr") or _SMTP["user"]
        if _addr:
            DEFAULT_FROM_EMAIL = f"MailPilot <{_addr}>"
            SERVER_EMAIL = DEFAULT_FROM_EMAIL
else:
    EMAIL_BACKEND = (os.environ.get("DJANGO_EMAIL_BACKEND") or "").strip() or (
        "django.core.mail.backends.console.EmailBackend"
    )

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "mailpilot-cache",
    }
}

# In-process APScheduler fallback poll when CELERY_BROKER_URL is unset (seconds, min 10).
_iv_raw = (os.environ.get("IMAP_POLL_SECONDS") or os.environ.get("MAIL_POLL_INTERVAL_SECONDS") or "60").strip()
try:
    MAIL_POLL_INTERVAL_SECONDS = max(10, min(int(_iv_raw or "60"), 86400))
except ValueError:
    MAIL_POLL_INTERVAL_SECONDS = 60

# Celery (optional — when set, use `celery -A mailpilot worker` and `celery -A mailpilot beat`)
CELERY_BROKER_URL = (os.environ.get("CELERY_BROKER_URL") or "").strip()
CELERY_RESULT_BACKEND = (os.environ.get("CELERY_RESULT_BACKEND") or CELERY_BROKER_URL).strip()
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {}
MAIL_POLL_BEAT_SECONDS = max(15, int((os.environ.get("MAIL_POLL_BEAT_SECONDS") or "120").strip() or "120"))
if CELERY_BROKER_URL:
    CELERY_BEAT_SCHEDULE["poll-all-mail"] = {
        "task": "core.tasks.poll_all_users_mail",
        "schedule": timedelta(seconds=MAIL_POLL_BEAT_SECONDS),
    }

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
_cookie_secure_env = (os.environ.get("DJANGO_COOKIE_SECURE") or "").strip().lower()
if _cookie_secure_env:
    SESSION_COOKIE_SECURE = _cookie_secure_env in ("1", "true", "yes")
else:
    # Default safe behavior: only force secure cookies when HTTPS redirect is enabled.
    # This keeps local HTTP dev working even when DEBUG=false (e.g. FLASK_DEBUG=false).
    SESSION_COOKIE_SECURE = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "").lower() in ("1", "true", "yes")
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Behind IIS / nginx reverse proxy: trust X-Forwarded-Host so request.get_host() matches the browser URL.
_xfh = (os.environ.get("DJANGO_USE_X_FORWARDED_HOST") or "").strip().lower()
if _xfh in ("0", "false", "no"):
    USE_X_FORWARDED_HOST = False
elif _xfh in ("1", "true", "yes"):
    USE_X_FORWARDED_HOST = True
else:
    USE_X_FORWARDED_HOST = not DEBUG
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "").lower() in ("1", "true", "yes")
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0") or "0")
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "").lower() in (
    "1",
    "true",
    "yes",
)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

def _norm_origin(o: str) -> str:
    return (o or "").strip().rstrip("/")


_csrf_origins_raw = os.environ.get(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "http://127.0.0.1,http://localhost,"
    "http://127.0.0.1:8011,http://localhost:8011",
)
CSRF_TRUSTED_ORIGINS = [_norm_origin(o) for o in _csrf_origins_raw.split(",") if _norm_origin(o)]

# If SITE_URL is set, trust it for CSRF (common reverse-proxy / custom domain setup).
if SITE_URL:
    if SITE_URL not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(SITE_URL)

# Also trust https://<allowed-host> for production domains.
if not DEBUG:
    for _h in ALLOWED_HOSTS or []:
        h = (_h or "").strip()
        if not h or h == "*":
            continue
        # Add both schemes to be safe if a proxy forwards http internally.
        for scheme in ("https://", "http://"):
            o = _norm_origin(f"{scheme}{h}")
            if o and o not in CSRF_TRUSTED_ORIGINS:
                CSRF_TRUSTED_ORIGINS.append(o)

# ---- REST API (DRF) ----
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        # Keep session auth for admin + web UI helpers.
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "MailPilot API",
    "DESCRIPTION": "MailPilot backend API (versioned, token-auth).",
    "VERSION": "1.0.0",
    # JWT bearer auth in Swagger UI
    "SECURITY": [{"bearerAuth": []}],
    "COMPONENT_SPLIT_REQUEST": True,
    "COMPONENT_SECURITY_SCHEMES": {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    },
}

# Short, mobile-friendly JWT defaults (override via env if needed)
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.environ.get("JWT_ACCESS_MINUTES", "30") or "30")
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.environ.get("JWT_REFRESH_DAYS", "14") or "14")
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
}
