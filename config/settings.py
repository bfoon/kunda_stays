import os
from pathlib import Path

from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
    "stays",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "stays.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "kunda"),
        "USER": env("POSTGRES_USER", "kunda"),
        "PASSWORD": env("POSTGRES_PASSWORD", "kunda"),
        "HOST": env("POSTGRES_HOST", "db"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Banjul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# --- Celery ---
CELERY_BROKER_URL = env("REDIS_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = None
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "release-expired-holds": {
        "task": "stays.tasks.release_expired_holds",
        "schedule": crontab(minute="*/15"),
    },
    "payment-reminders": {
        "task": "stays.tasks.send_payment_reminders",
        "schedule": crontab(hour=9, minute=0),
    },
    "checkin-reminders": {
        "task": "stays.tasks.send_checkin_reminders",
        "schedule": crontab(hour=10, minute=0),
    },
}

# --- Business configuration (all from environment) ---
KUNDA = {
    "name": env("BUSINESS_NAME", "Kunda Stays"),
    "tagline": env("BUSINESS_TAGLINE", "Serviced apartments by the Atlantic"),
    "phone": env("BUSINESS_PHONE", "+220 300 0000"),
    "whatsapp": env("BUSINESS_WHATSAPP", "2203000000"),
    "email": env("BUSINESS_EMAIL", "stay@kunda.gm"),
    "address": env("BUSINESS_ADDRESS", "Kairaba Avenue, Serrekunda, The Gambia"),
    "lat": env("BUSINESS_LAT", "13.4549"),
    "lng": env("BUSINESS_LNG", "-16.6790"),
    "default_country_code": env("DEFAULT_COUNTRY_CODE", "220"),
    "currency_code": env("CURRENCY_CODE", "GMD"),
    "currency_symbol": env("CURRENCY_SYMBOL", "D"),
    "hold_hours": int(env("BOOKING_HOLD_HOURS", "24")),
    "checkin_time": env("CHECKIN_TIME", "14:00"),
    "checkout_time": env("CHECKOUT_TIME", "11:00"),
    "site_url": env("SITE_URL", "http://localhost:8000").rstrip("/"),
    "wave_number": env("WAVE_NUMBER", "+220 300 0000"),
    "afrimoney_number": env("AFRIMONEY_NUMBER", "+220 700 0000"),
    "qmoney_number": env("QMONEY_NUMBER", "+220 600 0000"),
    "bank_details": env("BANK_DETAILS", "Trust Bank Gambia · Kunda Stays Ltd · Acc 0000000000"),
    "whatsapp_token": env("WHATSAPP_TOKEN", ""),
    "whatsapp_phone_id": env("WHATSAPP_PHONE_NUMBER_ID", ""),
    "whatsapp_api_version": env("WHATSAPP_API_VERSION", "v21.0"),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
