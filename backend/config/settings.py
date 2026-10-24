"""Race Center - configuracion de la aplicacion Django.

Proyecto **personal** (uso familiar). Por defecto todo escucha solo en
loopback y no hay exposicion a Internet.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

# El .env vive en la raiz del proyecto (un unico archivo para todo el stack).
load_dotenv(PROJECT_ROOT / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Aplicacion
# --------------------------------------------------------------------------- #

APP_NAME = os.environ.get("APP_NAME", "Race Center")
APP_MODE = os.environ.get("APP_MODE", "personal")
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "America/Argentina/Cordoba")
APP_DEBUG = env_bool("APP_DEBUG", True)

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "race-center-dev-local-only-cambiar-en-produccion-personal",
)

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "core",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.gzip.GZipMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --------------------------------------------------------------------------- #
# Base de datos
# --------------------------------------------------------------------------- #

DATABASE_ENGINE = os.environ.get("DATABASE_ENGINE", "sqlite")
if DATABASE_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            # En el contenedor la base vive en el volumen persistente, no en el
            # codigo: si no, cada redespliegue perderia el historico.
            "NAME": os.environ.get("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3")),
            "OPTIONS": {"timeout": 20},
        }
    }
else:
    # MySQL queda preparado para una etapa posterior.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("MYSQL_DATABASE", "race_center"),
            "USER": os.environ.get("MYSQL_USER", "racecenter"),
            "PASSWORD": os.environ.get("MYSQL_PASSWORD", ""),
            "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
            "PORT": os.environ.get("MYSQL_PORT", "3306"),
        }
    }

AUTH_PASSWORD_VALIDATORS: list[dict[str, str]] = []

LANGUAGE_CODE = "es-ar"
TIME_ZONE = APP_TIMEZONE
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------- #
# SQLite con dos procesos (ingesta + API)
#
# En el contenedor (y tambien en local) hay dos procesos escribiendo y
# leyendo la misma base: la ingesta escribe los snapshots y la API los
# sirve. Sin WAL aparecen "database is locked" de forma intermitente.
# --------------------------------------------------------------------------- #
if DATABASE_ENGINE == "sqlite":
    from django.db.backends.signals import connection_created
    from django.dispatch import receiver

    @receiver(connection_created)
    def _activar_wal(sender, connection, **kwargs):  # pragma: no cover
        if connection.vendor != "sqlite":
            return
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")

# --------------------------------------------------------------------------- #
# DRF
# --------------------------------------------------------------------------- #

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
}

# --------------------------------------------------------------------------- #
# Seguridad y red
# --------------------------------------------------------------------------- #

ENABLE_PUBLIC_ACCESS = env_bool("ENABLE_PUBLIC_ACCESS", False)
ENABLE_LAN_ACCESS = env_bool("ENABLE_LAN_ACCESS", False)

BACKEND_HOST = os.environ.get("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = env_int("BACKEND_PORT", 8000)
FRONTEND_HOST = os.environ.get("FRONTEND_HOST", "127.0.0.1")
FRONTEND_PORT = env_int("FRONTEND_PORT", 5173)

if ENABLE_PUBLIC_ACCESS:
    ALLOWED_HOSTS = ["*"]
elif ENABLE_LAN_ACCESS:
    # Modo domestico: se permiten los hosts de la LAN configurados.
    ALLOWED_HOSTS = ["127.0.0.1", "localhost", "0.0.0.0"]
    allowed = os.environ.get("LAN_ALLOWED_HOSTS", "")
    ALLOWED_HOSTS.extend([host.strip() for host in allowed.split(",") if host.strip()])
else:
    ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

# CORS limitado al frontend local. Nunca abierto indiscriminadamente.
CORS_ALLOWED_ORIGINS = [
    "http://%s:%d" % (FRONTEND_HOST, FRONTEND_PORT),
    "http://localhost:%d" % FRONTEND_PORT,
    "http://127.0.0.1:%d" % FRONTEND_PORT,
]
if ENABLE_LAN_ACCESS:
    lan_origins = os.environ.get("LAN_ALLOWED_ORIGINS", "")
    CORS_ALLOWED_ORIGINS.extend(
        [origin.strip() for origin in lan_origins.split(",") if origin.strip()]
    )
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = list(CORS_ALLOWED_ORIGINS)

# --------------------------------------------------------------------------- #
# Detras de un proxy inverso (Coolify / nginx terminates TLS)
#
# Sin esto, Django cree que la peticion llego por HTTP y genera URLs y
# redirecciones http:// en vez de https://.
# --------------------------------------------------------------------------- #
if env_bool("TRUST_PROXY_SSL", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

# --------------------------------------------------------------------------- #
# Proveedores de datos
# --------------------------------------------------------------------------- #

DATA_PROVIDER = os.environ.get("DATA_PROVIDER", "auto")
LIVE_PROVIDER = os.environ.get("LIVE_PROVIDER", "free_livetiming")
HISTORICAL_PROVIDER = os.environ.get("HISTORICAL_PROVIDER", "openf1")
METADATA_PROVIDER = os.environ.get("METADATA_PROVIDER", "jolpica")

F1_LIVETIMING_URL = os.environ.get("F1_LIVETIMING_URL", "http://127.0.0.1:3000")
OPENF1_BASE_URL = os.environ.get("OPENF1_BASE_URL", "https://api.openf1.org/v1")
OPENF1_LIVE_ENABLED = env_bool("OPENF1_LIVE_ENABLED", False)
OPENF1_API_KEY = os.environ.get("OPENF1_API_KEY") or None
JOLPICA_BASE_URL = os.environ.get("JOLPICA_BASE_URL", "https://api.jolpi.ca/ergast/f1")

# Datos sinteticos: desactivados. El dashboard real nunca muestra fixtures.
ENABLE_MOCK_DATA = env_bool("ENABLE_MOCK_DATA", False)

# Frecuencia de ingesta y umbrales de frescura.
INGEST_POLL_SECONDS = env_float("INGEST_POLL_SECONDS", 3.0)
INGEST_HTTP_TIMEOUT = env_float("INGEST_HTTP_TIMEOUT", 10.0)
LIVE_MAX_AGE_SECONDS = env_float("LIVE_MAX_AGE_SECONDS", 90.0)
DELAYED_MAX_AGE_SECONDS = env_float("DELAYED_MAX_AGE_SECONDS", 300.0)

# --------------------------------------------------------------------------- #
# Sesion de clasificacion objetivo (la del evento prioritario)
# --------------------------------------------------------------------------- #

TARGET_SESSION_KEY = os.environ.get("TARGET_SESSION_KEY", "") or None

# --------------------------------------------------------------------------- #
# Varios
# --------------------------------------------------------------------------- #

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "racecenter": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "httpx": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
