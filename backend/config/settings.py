"""
Django settings for the GramSentinel prototype.

GramSentinel — Rural Healthcare Intelligence & Community Early-Warning Platform.
Prototype only: synthetic / public / anonymised data. No real patient data.
"""

from datetime import timedelta
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

load_dotenv(REPO_ROOT / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "dev-only-insecure-key-change-me-in-any-real-deployment",
)

# Render assigns every web service a hostname and exposes it to the running
# process via this variable — trust it automatically so a Render deployment
# does not need ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS set by hand for the
# happy path. Custom domains still go through the explicit env vars below.
# Read once, up here, because DEBUG's default (right below) also uses it.
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")

# DEBUG defaults to True for local development convenience, exactly as
# before — but only when RENDER_EXTERNAL_HOSTNAME is absent. On Render that
# variable is always present, so the *default* there is False even if the
# DEBUG env var itself was never explicitly set on the service (this is not
# hypothetical: it happened). An explicit DEBUG env var — set to either
# value, on either platform — still always wins; this only changes what
# happens when nobody set one.
DEBUG = env_bool("DEBUG", default=not RENDER_EXTERNAL_HOSTNAME)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0,testserver")

if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

INSTALLED_APPS = [
    # Daphne must precede staticfiles so runserver uses the ASGI server.
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "channels",
    # GramSentinel apps
    "core",
    "users",
    "patients",
    "assessments",
    "community",
    "alerts",
    "integrations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Real-time is optional in the MVP: an in-memory layer is enough for a single
# demo process, and every feature must work without WebSockets.
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

# SQLite by default (zero setup for local dev and CI), using the same
# BASE_DIR-anchored absolute path as before — deliberately independent of
# CWD or how the value is spelled. Setting DATABASE_URL to a postgres:// URL
# — which Render's PostgreSQL add-on provides automatically once attached —
# switches to that database with no other change required. Only postgres
# schemes are honoured here: dj_database_url's sqlite:// parsing resolves
# relative paths against the process CWD rather than BASE_DIR, which is a
# footgun this project has no reason to take on since SQLite is local-dev-only.
import dj_database_url  # noqa: E402

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith(("postgres://", "postgresql://")):
    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=int(os.getenv("DB_CONN_MAX_AGE", "60")),
            ssl_require=env_bool("DATABASE_SSL_REQUIRE", False),
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        # Deny by default; every view opts in explicitly with a role permission.
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "EXCEPTION_HANDLER": "config.exceptions.gramsentinel_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
CORS_ALLOW_CREDENTIALS = True

# CSRF only matters for same-origin, cookie/session-based requests — i.e. the
# Django admin login at /admin/, not the JWT-bearer API the React app uses.
# The backend's own Render URL is trusted automatically for that reason.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")
if RENDER_EXTERNAL_HOSTNAME:
    _render_origin = f"https://{RENDER_EXTERNAL_HOSTNAME}"
    if _render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_render_origin)

# ---------------------------------------------------------------------------
# Production security hardening
# ---------------------------------------------------------------------------
# Every setting below is gated on `not DEBUG`, so a local `python manage.py
# runserver` (DEBUG=True by default) is completely unaffected. They only take
# effect once DEBUG=False is set explicitly, which is how Render is
# configured (see RENDER_DEPLOYMENT.md).

# Render terminates TLS at its edge and forwards the original scheme in this
# header; without telling Django to trust it, request.is_secure() is always
# False behind the proxy and the settings below would never engage.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_REFERRER_POLICY = "same-origin"

# Starts conservative (1 hour) so a misconfiguration is never more than an
# hour of pain; raise via the env var once HTTPS is confirmed working end to
# end (see RENDER_DEPLOYMENT.md). include-subdomains/preload are left off —
# both are effectively one-way switches and this app owns no subdomains.
SECURE_HSTS_SECONDS = 0 if DEBUG else int(os.getenv("SECURE_HSTS_SECONDS", "3600"))

# ---------------------------------------------------------------------------
# GramSentinel platform configuration
# ---------------------------------------------------------------------------

# LLM is used only for synthesis / plain-language explanation and is never in
# the safety-critical path. Absence of a key must degrade gracefully.
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.anthropic.com/v1/messages")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5")
LLM_ENABLED = env_bool("LLM_ENABLED", bool(LLM_API_KEY))
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "12"))

GRAMSENTINEL = {
    # Deterministic Safety Engine thresholds (Section 11 / 15 of the spec).
    "MIN_INDEPENDENT_SOURCES": 2,
    "TEMPORAL_WINDOW_DAYS": 10,
    "MIN_DATA_QUALITY_RATIO": 0.6,
    # Anomaly thresholds per source kind (percentage change vs own baseline).
    "ANOMALY_THRESHOLDS": {
        "CHW": 40.0,
        "PHC": 30.0,
        "PHARMACY": 30.0,
        "SCHOOL": 50.0,
        "RURALCARE_AGGREGATE": 40.0,
    },
    # School absenteeism also triggers on absolute percentage-point rise.
    "SCHOOL_ABSOLUTE_POINT_RISE": 5.0,
    "LAB_MIN_CONFIRMATIONS": 1,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(levelname)s %(name)s :: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "gramsentinel": {
            "handlers": ["console"],
            "level": os.getenv("GRAMSENTINEL_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
