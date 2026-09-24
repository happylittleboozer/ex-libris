"""Settings for the Ex Libris project."""

import sys
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, True))
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env("DEBUG")

# A missing production secret must stop the process. Local runs can start
# without one because .env is not required for a fresh checkout.
if DEBUG:
    SECRET_KEY = env("SECRET_KEY", default="dev-only-insecure-key")
else:
    SECRET_KEY = env("SECRET_KEY")

ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1"] if DEBUG else [],
)

# An empty key disables the form assistant. The admin form still saves.
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")

GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default="")
# Both values are required. A half-configured client must not show the button.
GOOGLE_LOGIN_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "storages",
    "library",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if not DEBUG:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "exlibris.urls"

SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LOGIN_REDIRECT_URL = "/admin/"
# Google already verified the address. A new user should reach the admin
# without a second confirmation step, and there is no local allauth signup.
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_ONLY = True
SOCIALACCOUNT_ADAPTER = "library.adapters.StaffSocialAccountAdapter"

google_provider = {
    "SCOPE": ["openid", "email", "profile"],
    "AUTH_PARAMS": {"access_type": "online"},
    "OAUTH_PKCE_ENABLED": True,
}
if GOOGLE_LOGIN_ENABLED:
    google_provider["APPS"] = [
        {
            "client_id": GOOGLE_CLIENT_ID,
            "secret": GOOGLE_CLIENT_SECRET,
            "key": "",
        }
    ]
SOCIALACCOUNT_PROVIDERS = {"google": google_provider}

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
                "library.context_processors.google_login",
            ],
        },
    },
]

WSGI_APPLICATION = "exlibris.wsgi.application"

database_url = env("DATABASE_URL", default="")
if database_url:
    DATABASES = {"default": environ.Env.db_url_config(database_url)}
    # Neon's pooled host is a transaction pooler. A persistent Django
    # connection would pin a server connection across requests.
    if "pooler" in database_url:
        DATABASES["default"]["CONN_MAX_AGE"] = 0
elif DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured("DATABASE_URL is required when DEBUG is off.")

# The pooled Neon host cannot create a separate test database. Lending-rule
# tests use SQLite so a test run never writes to the dev branch.
if "test" in sys.argv:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Tallinn"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# A librarian stays signed in for one desk shift, then has to sign in again.
SESSION_COOKIE_AGE = 60 * 60 * 8
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
if not DEBUG:
    # Render terminates TLS and forwards plain HTTP. Trust the proxy's scheme
    # so secure cookies and redirects see the original HTTPS request.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

# Tests stay on local storage so they do not upload covers to R2.
r2_settings = {
    "AWS_ACCESS_KEY_ID": env("AWS_ACCESS_KEY_ID", default=""),
    "AWS_SECRET_ACCESS_KEY": env("AWS_SECRET_ACCESS_KEY", default=""),
    "AWS_S3_ENDPOINT_URL": env("AWS_S3_ENDPOINT_URL", default=""),
    "AWS_STORAGE_BUCKET_NAME": env("AWS_STORAGE_BUCKET_NAME", default=""),
    "AWS_S3_CUSTOM_DOMAIN": env("AWS_S3_CUSTOM_DOMAIN", default=""),
}
r2_settings["AWS_S3_CUSTOM_DOMAIN"] = (
    r2_settings["AWS_S3_CUSTOM_DOMAIN"].removeprefix("https://").removeprefix("http://").strip("/")
)
USE_R2 = "test" not in sys.argv and all(r2_settings.values())
if USE_R2:
    globals().update(r2_settings)
    AWS_S3_REGION_NAME = "auto"
    AWS_S3_ADDRESSING_STYLE = "path"
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_S3_FILE_OVERWRITE = True
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = False
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {
            "BACKEND": (
                "whitenoise.storage.CompressedManifestStaticFilesStorage"
                if not DEBUG
                else "django.contrib.staticfiles.storage.StaticFilesStorage"
            ),
        },
    }
elif DEBUG or "test" in sys.argv:
    USE_R2 = False
else:
    raise ImproperlyConfigured("R2 storage settings are required when DEBUG is off.")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
