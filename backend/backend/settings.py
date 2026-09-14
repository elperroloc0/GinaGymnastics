import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


load_dotenv(BASE_DIR / ".env")

# One Redis instance, split by database: /0 Celery broker, /1 channel layer,
# /2 cache. REDIS_URL must not carry a db number - any path is dropped here.
_redis = urlsplit(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379"))
REDIS_BASE_URL = urlunsplit((_redis.scheme, _redis.netloc, "", "", ""))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"

if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set in the environment when DEBUG=False"
        )
    SECRET_KEY = "django-insecure-dev-only-DO-NOT-USE-IN-PRODUCTION"


_allowed_hosts_env = os.environ.get("ALLOWED_HOSTS")
if _allowed_hosts_env is None:
    _allowed_hosts_env = "localhost, 127.0.0.1," if DEBUG else ""

ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_env.split(",") if h.strip()]

if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set when DEBUG=False")

CSRF_TRUSTED_ORIGINS = [
    f"https://{h}" for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1", "testserver")
]

# Frontend is a separate origin (Vercel), so the browser needs explicit CORS
# headers on API responses - ALLOWED_HOSTS/CSRF_TRUSTED_ORIGINS above don't
# cover this, they're about the Host header and CSRF, not CORS.
_cors_allowed_origins_env = os.environ.get("CORS_ALLOWED_ORIGINS")
if _cors_allowed_origins_env is None:
    _cors_allowed_origins_env = "http://localhost:5173," if DEBUG else ""

CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_allowed_origins_env.split(",") if o.strip()]

if not DEBUG and not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured("CORS_ALLOWED_ORIGINS must be set when DEBUG=False")

# "django" is the compose service name: traccar posts webhooks to
# http://django:8000/, and the container healthcheck sends the same Host.
# Only reachable from inside the compose network - caddy, the sole public
# entrypoint, serves the DOMAIN host only and never forwards this one.
# Added after CSRF_TRUSTED_ORIGINS so it stays out of that list.
if "django" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("django")

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

if not DEBUG:
    # Caddy terminates TLS in front of us (SECURE_PROXY_SSL_HEADER above), so
    # these are safe to force unconditionally once DEBUG is off - there is no
    # real production request that isn't already HTTPS.
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True


# Application definition
INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'corsheaders',

    'accounts.apps.AccountsConfig',

    'fleet.apps.FleetConfig',

    'tracking.apps.TrackingConfig',

    'notifications.apps.NotificationsConfig',

    # third party model field for phone #:
    'phonenumber_field',

    # django rest
    'rest_framework',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# JWT auth is always on. In DEBUG we additionally accept Basic/Session so the
# browsable API (api-auth/) still works for manual poking - previously this
# branch REPLACED JWTAuthentication instead of adding to it, which meant a
# real `Authorization: Bearer <token>` header was silently ignored whenever
# DEBUG=True (i.e. every local dev run), and every IsAuthenticated endpoint
# 401'd for a real frontend request even with a valid token.
DEFAULT_AUTHENTICATION_CLASSES = ['rest_framework_simplejwt.authentication.JWTAuthentication']

if DEBUG:
    DEFAULT_AUTHENTICATION_CLASSES += [
        'rest_framework.authentication.BasicAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ]


REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES' : DEFAULT_AUTHENTICATION_CLASSES,
    'DEFAULT_PERMISSION_CLASSES' : [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'login': '10/min',
        'set_password': '10/min',
    },
}


# Celery Configuration
CELERY_BROKER_URL = f"{REDIS_BASE_URL}/0"

CELERY_TASK_TIME_LIMIT = 30 * 60


ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'

ASGI_APPLICATION = "backend.asgi.application"


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# overwrite database settings if DATABASE_URL is provided (render)
db_from_env = dj_database_url.config(conn_max_age=600, ssl_require=False)
if db_from_env:
    DATABASES['default'].update(db_from_env)

# custom user model access
AUTH_USER_MODEL = 'accounts.User'

# Login accepts username, email, or phone number - see accounts/backends.py.
AUTHENTICATION_BACKENDS = [
    'accounts.backends.FlexibleLoginBackend',
]


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'America/New_York'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'


CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [f"{REDIS_BASE_URL}/1"],
        },
    },
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"{REDIS_BASE_URL}/2",
        "OPTIONS": {
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
        }
    }
}
