import os
import ssl
from pathlib import Path
from datetime import timedelta
from urllib.parse import quote_plus
from django.core.exceptions import ImproperlyConfigured


def _validate_tls_cert_paths(paths, service_name):
    """Validate that configured TLS certificate file paths exist on disk.

    Raises ImproperlyConfigured with a clear message identifying the
    service and missing file so operators can fix their environment.
    """
    for env_var, file_path in paths:
        if file_path and not Path(file_path).is_file():
            raise ImproperlyConfigured(
                f"{service_name} TLS: {env_var}={file_path!r} — file not found. "
                f"Check that the certificate file exists and the volume is mounted correctly."
            )

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_DB = os.environ.get("REDIS_DB", "0")
REDIS_USER = os.environ.get("REDIS_USER", "")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")

# Redis TLS configuration
REDIS_SSL = os.environ.get("REDIS_SSL", "false").lower() == "true"
REDIS_SSL_VERIFY = os.environ.get("REDIS_SSL_VERIFY", "true").lower() == "true"
REDIS_SSL_CA_CERT = os.environ.get("REDIS_SSL_CA_CERT", "")
REDIS_SSL_CERT = os.environ.get("REDIS_SSL_CERT", "")
REDIS_SSL_KEY = os.environ.get("REDIS_SSL_KEY", "")

# Reusable dict of SSL kwargs for redis.Redis() constructors
REDIS_SSL_PARAMS = {}
if REDIS_SSL:
    _validate_tls_cert_paths([
        ("REDIS_SSL_CA_CERT", REDIS_SSL_CA_CERT),
        ("REDIS_SSL_CERT", REDIS_SSL_CERT),
        ("REDIS_SSL_KEY", REDIS_SSL_KEY),
    ], "Redis")

    REDIS_SSL_PARAMS["ssl"] = True
    REDIS_SSL_PARAMS["ssl_cert_reqs"] = ssl.CERT_REQUIRED if REDIS_SSL_VERIFY else ssl.CERT_NONE
    if REDIS_SSL_CA_CERT:
        REDIS_SSL_PARAMS["ssl_ca_certs"] = REDIS_SSL_CA_CERT
    if REDIS_SSL_CERT:
        REDIS_SSL_PARAMS["ssl_certfile"] = REDIS_SSL_CERT
    if REDIS_SSL_KEY:
        REDIS_SSL_PARAMS["ssl_keyfile"] = REDIS_SSL_KEY

    _mtls = "enabled" if REDIS_SSL_CERT and REDIS_SSL_KEY else "disabled"
    _verify = "on" if REDIS_SSL_VERIFY else "off"
    print(f"Redis TLS: enabled (verify={_verify}, mTLS={_mtls})")
else:
    print("Redis TLS: disabled")

# Set DEBUG to True for development, False for production
if os.environ.get("DISPATCHARR_DEBUG", "False").lower() == "true":
    DEBUG = True
else:
    DEBUG = False

ALLOWED_HOSTS = ["*"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "apps.api",
    "apps.accounts",
    "apps.backups.apps.BackupsConfig",
    "apps.channels.apps.ChannelsConfig",
    "apps.dashboard",
    "apps.epg",
    "apps.hdhr",
    "apps.m3u",
    "apps.output",
    "apps.proxy.apps.ProxyConfig",
    "apps.proxy.ts_proxy",
    "apps.vod.apps.VODConfig",
    "apps.connect.apps.ConnectConfig",
    "core",
    "daphne",
    "drf_spectacular",
    "channels",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "django_filters",
    "django_celery_beat",
    "apps.plugins",
]

# EPG Processing optimization settings
EPG_BATCH_SIZE = 1000  # Number of records to process in a batch
EPG_MEMORY_LIMIT = 512  # Memory limit in MB before forcing garbage collection
EPG_ENABLE_MEMORY_MONITORING = True  # Whether to monitor memory usage during processing

# XtreamCodes Rate Limiting Settings
# Delay between profile authentications when refreshing multiple profiles
# This prevents providers from temporarily banning users with many profiles
XC_PROFILE_REFRESH_DELAY = float(os.environ.get('XC_PROFILE_REFRESH_DELAY', '2.5'))  # seconds between profile refreshes

# Database optimization settings
DATABASE_STATEMENT_TIMEOUT = 300  # Seconds before timing out long-running queries
DATABASE_CONN_MAX_AGE = (
    60  # Connection max age in seconds, helps with frequent reconnects
)

# Disable atomic requests for performance-sensitive views
ATOMIC_REQUESTS = False

# Cache settings - add caching for EPG operations
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "dispatcharr-epg-cache",
        "TIMEOUT": 3600,  # 1 hour cache timeout
        "OPTIONS": {
            "MAX_ENTRIES": 10000,
            "CULL_FREQUENCY": 3,  # Purge 1/3 of entries when max is reached
        },
    }
}

# Timeouts for external connections
REQUESTS_TIMEOUT = 30  # Seconds for external API requests

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "corsheaders.middleware.CorsMiddleware",
]


ROOT_URLCONF = "dispatcharr.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "frontend/dist"), BASE_DIR / "templates"],
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

WSGI_APPLICATION = "dispatcharr.wsgi.application"
ASGI_APPLICATION = "dispatcharr.asgi.application"

_redis_scheme = "rediss" if REDIS_SSL else "redis"

# URL-encoded auth string shared by CHANNEL_LAYERS and Celery broker URLs
if REDIS_PASSWORD:
    _encoded_password = quote_plus(REDIS_PASSWORD)
    if REDIS_USER:
        _redis_auth = f"{quote_plus(REDIS_USER)}:{_encoded_password}@"
    else:
        _redis_auth = f":{_encoded_password}@"
else:
    _redis_auth = ""

_channels_redis_url = f"{_redis_scheme}://{_redis_auth}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
# channels_redis accepts either a URL string or a dict with "address" + kwargs.
# When TLS is enabled, pass SSL params alongside the URL so the connection pool
# uses the correct CA cert and verification settings.
if REDIS_SSL:
    # Filter out "ssl" key — the rediss:// scheme already enables SSL.
    # Passing ssl=True as a kwarg to aioredis from_url causes an error.
    _channels_ssl = {k: v for k, v in REDIS_SSL_PARAMS.items() if k != "ssl"}
    _channels_host = {"address": _channels_redis_url, **_channels_ssl}
else:
    _channels_host = _channels_redis_url

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [_channels_host],
        },
    },
}

# PostgreSQL TLS configuration (defined before DATABASES for module-level access)
POSTGRES_SSL = os.environ.get("POSTGRES_SSL", "false").lower() == "true"
POSTGRES_SSL_MODE = os.environ.get("POSTGRES_SSL_MODE", "verify-full")
POSTGRES_SSL_CA_CERT = os.environ.get("POSTGRES_SSL_CA_CERT", "")
POSTGRES_SSL_CERT = os.environ.get("POSTGRES_SSL_CERT", "")
POSTGRES_SSL_KEY = os.environ.get("POSTGRES_SSL_KEY", "")

if os.getenv("DB_ENGINE", None) == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": "/data/dispatcharr.db",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "dispatcharr"),
            "USER": os.environ.get("POSTGRES_USER", "dispatch"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "secret"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": int(os.environ.get("POSTGRES_PORT", 5432)),
            "CONN_MAX_AGE": DATABASE_CONN_MAX_AGE,
        }
    }

    if POSTGRES_SSL:
        _validate_tls_cert_paths([
            ("POSTGRES_SSL_CA_CERT", POSTGRES_SSL_CA_CERT),
            ("POSTGRES_SSL_CERT", POSTGRES_SSL_CERT),
            ("POSTGRES_SSL_KEY", POSTGRES_SSL_KEY),
        ], "PostgreSQL")

        DATABASES["default"]["OPTIONS"] = {
            "sslmode": POSTGRES_SSL_MODE,
        }
        if POSTGRES_SSL_CA_CERT:
            DATABASES["default"]["OPTIONS"]["sslrootcert"] = POSTGRES_SSL_CA_CERT
        if POSTGRES_SSL_CERT:
            DATABASES["default"]["OPTIONS"]["sslcert"] = POSTGRES_SSL_CERT
        if POSTGRES_SSL_KEY:
            DATABASES["default"]["OPTIONS"]["sslkey"] = POSTGRES_SSL_KEY

        _mtls = "enabled" if POSTGRES_SSL_CERT and POSTGRES_SSL_KEY else "disabled"
        print(f"PostgreSQL TLS: enabled (sslmode={POSTGRES_SSL_MODE}, mTLS={_mtls})")
    else:
        print("PostgreSQL TLS: disabled")

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
]

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "apps.accounts.authentication.ApiKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "apps.accounts.permissions.IsAdmin",
    ],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        "login": "3/minute",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Dispatcharr API",
    "DESCRIPTION": "API documentation for Dispatcharr",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"  # Directory where static files will be collected

# Adjust STATICFILES_DIRS to include the paths to the directories that contain your static files.
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "frontend/dist"),  # React build static files
]


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

_default_redis_url = f"{_redis_scheme}://{_redis_auth}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
# Celery/Kombu require SSL parameters in the URL query string because
# internal URL parsing can overwrite the CELERY_BROKER_USE_SSL dict.
if REDIS_SSL:
    _celery_ssl_params = [
        f"ssl_cert_reqs={'CERT_REQUIRED' if REDIS_SSL_VERIFY else 'CERT_NONE'}",
    ]
    if REDIS_SSL_CA_CERT:
        _celery_ssl_params.append(f"ssl_ca_certs={REDIS_SSL_CA_CERT}")
    if REDIS_SSL_CERT:
        _celery_ssl_params.append(f"ssl_certfile={REDIS_SSL_CERT}")
    if REDIS_SSL_KEY:
        _celery_ssl_params.append(f"ssl_keyfile={REDIS_SSL_KEY}")
    _default_celery_url = f"{_default_redis_url}?{'&'.join(_celery_ssl_params)}"
else:
    _default_celery_url = _default_redis_url
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", _default_celery_url)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)

# Validate that URL overrides don't conflict with TLS settings
for _url_var, _url_val in [
    ("CELERY_BROKER_URL", CELERY_BROKER_URL),
    ("CELERY_RESULT_BACKEND", CELERY_RESULT_BACKEND),
]:
    _is_override = os.environ.get(_url_var) is not None
    if not _is_override:
        continue
    _url_is_ssl = _url_val.startswith("rediss://")
    if REDIS_SSL and not _url_is_ssl:
        raise ImproperlyConfigured(
            f"REDIS_SSL is enabled but {_url_var} uses redis:// (plaintext). "
            f"Change the URL scheme to rediss:// or remove the {_url_var} override."
        )
    if not REDIS_SSL and _url_is_ssl:
        raise ImproperlyConfigured(
            f"{_url_var} uses rediss:// (TLS) but REDIS_SSL is not enabled. "
            f"Set REDIS_SSL=true and configure the TLS certificate settings."
        )

# Celery TLS configuration — required in addition to the rediss:// URL scheme.
# Uses the same cert params as REDIS_SSL_PARAMS, minus the "ssl" key that
# redis-py needs but Celery/Kombu does not.
if REDIS_SSL:
    CELERY_BROKER_USE_SSL = {k: v for k, v in REDIS_SSL_PARAMS.items() if k != "ssl"}
    CELERY_RESULT_BACKEND_USE_SSL = CELERY_BROKER_USE_SSL

# Configure Redis key prefix
CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS = {
    "global_keyprefix": "celery-tasks:",  # Set the Redis key prefix for Celery
}

# Set TTL (Time-to-Live) for task results (in seconds)
CELERY_RESULT_EXPIRES = 3600  # 1 hour TTL for task results

# Optionally, set visibility timeout for task retries (if using Redis)
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "visibility_timeout": 3600,  # Time in seconds that a task remains invisible during retries
}

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"

# Worker memory safety net: recycle prefork workers exceeding 512MB RSS.
# Prevents unbounded growth from memory fragmentation or unexpected leaks.
CELERY_WORKER_MAX_MEMORY_PER_CHILD = 524_288  # 512 MB in KB

CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers.DatabaseScheduler"
CELERY_BEAT_SCHEDULE = {
    # Explicitly disable the old fetch-channel-statuses task
    # This ensures it gets disabled when DatabaseScheduler syncs
    "fetch-channel-statuses": {
        "task": "apps.proxy.tasks.fetch_channel_stats",
        "schedule": 2.0,  # Original schedule (doesn't matter since disabled)
        "enabled": False,  # Explicitly disabled
    },
    # Keep the file scanning task
    "scan-files": {
        "task": "core.tasks.scan_and_process_files",  # Direct task call
        "schedule": 20.0,  # Every 20 seconds
    },
    "maintain-recurring-recordings": {
        "task": "apps.channels.tasks.maintain_recurring_recordings",
        "schedule": 3600.0,  # Once an hour ensure recurring schedules stay ahead
    },
    # Check for version updates daily
    "check-version-updates": {
        "task": "core.tasks.check_for_version_update",
        "schedule": 86400.0,  # Once every 24 hours
    },
    # Check for account expirations daily
    "check-account-expirations": {
        "task": "apps.m3u.tasks.check_account_expirations",
        "schedule": 86400.0,  # Once every 24 hours
    },
}

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

# Backup settings
BACKUP_ROOT = os.environ.get("BACKUP_ROOT", "/data/backups")
BACKUP_DATA_DIRS = [
    os.environ.get("LOGOS_DIR", "/data/logos"),
    os.environ.get("UPLOADS_DIR", "/data/uploads"),
    os.environ.get("PLUGINS_DIR", "/data/plugins"),
]

SERVER_IP = "127.0.0.1"

CORS_ALLOW_ALL_ORIGINS = True
CSRF_TRUSTED_ORIGINS = ["http://*", "https://*"]
APPEND_SLASH = True

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": False,  # Optional: Whether to rotate refresh tokens
    "BLACKLIST_AFTER_ROTATION": True,  # Optional: Whether to blacklist refresh tokens
}

# Redis connection settings — _default_redis_url uses rediss:// when REDIS_SSL is enabled
REDIS_URL = os.environ.get("REDIS_URL", _default_redis_url)
if os.environ.get("REDIS_URL") is not None:
    if REDIS_SSL and not REDIS_URL.startswith("rediss://"):
        raise ImproperlyConfigured(
            "REDIS_SSL is enabled but REDIS_URL uses redis:// (plaintext). "
            "Change the URL scheme to rediss:// or remove the REDIS_URL override."
        )
    if not REDIS_SSL and REDIS_URL.startswith("rediss://"):
        raise ImproperlyConfigured(
            "REDIS_URL uses rediss:// (TLS) but REDIS_SSL is not enabled. "
            "Set REDIS_SSL=true and configure the TLS certificate settings."
        )
REDIS_SOCKET_TIMEOUT = 60  # Socket timeout in seconds
REDIS_SOCKET_CONNECT_TIMEOUT = 5  # Connection timeout in seconds
REDIS_HEALTH_CHECK_INTERVAL = 15  # Health check every 15 seconds
REDIS_SOCKET_KEEPALIVE = True  # Enable socket keepalive
REDIS_RETRY_ON_TIMEOUT = True  # Retry on timeout
REDIS_MAX_RETRIES = 10  # Maximum number of retries
REDIS_RETRY_INTERVAL = 1  # Initial retry interval in seconds

# Proxy Settings
PROXY_SETTINGS = {
    "HLS": {
        "DEFAULT_URL": "",  # Default HLS stream URL if needed
        "BUFFER_SIZE": 1000,
        "USER_AGENT": "VLC/3.0.20 LibVLC/3.0.20",
        "CHUNK_SIZE": 8192,
        "CLIENT_POLL_INTERVAL": 0.1,
        "MAX_RETRIES": 3,
        "MIN_SEGMENTS": 12,
        "MAX_SEGMENTS": 16,
        "WINDOW_SIZE": 12,
        "INITIAL_SEGMENTS": 3,
    },
    "TS": {
        "DEFAULT_URL": "",  # Default TS stream URL if needed
        "BUFFER_SIZE": 1000,
        "RECONNECT_DELAY": 5,
        "USER_AGENT": "VLC/3.0.20 LibVLC/3.0.20",
    },
}

# Map log level names to their numeric values
LOG_LEVEL_MAP = {
    "TRACE": 5,
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

# Get log level from environment variable, default to INFO if not set
# Add debugging output to see exactly what's being detected
env_log_level = os.environ.get("DISPATCHARR_LOG_LEVEL", "")
print(f"Environment DISPATCHARR_LOG_LEVEL detected as: '{env_log_level}'")

if not env_log_level:
    print("No DISPATCHARR_LOG_LEVEL found in environment, using default INFO")
    LOG_LEVEL_NAME = "INFO"
else:
    LOG_LEVEL_NAME = env_log_level.upper()
    print(f"Setting log level to: {LOG_LEVEL_NAME}")

LOG_LEVEL = LOG_LEVEL_MAP.get(LOG_LEVEL_NAME, 20)  # Default to INFO (20) if invalid

# Add this to your existing LOGGING configuration or create one if it doesn't exist
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "level": 5,  # Always allow TRACE level messages through the handler
        },
    },
    "loggers": {
        "core.tasks": {
            "handlers": ["console"],
            "level": LOG_LEVEL,  # Use environment-configured level
            "propagate": False,  # Don't propagate to root logger to avoid duplicate logs
        },
        "core.utils": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "apps.proxy": {
            "handlers": ["console"],
            "level": LOG_LEVEL,  # Use environment-configured level
            "propagate": False,  # Don't propagate to root logger
        },
        # Add parent logger for all app modules
        "apps": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        # Celery loggers to capture task execution messages
        "celery": {
            "handlers": ["console"],
            "level": LOG_LEVEL,  # Use configured log level for Celery logs
            "propagate": False,
        },
        "celery.task": {
            "handlers": ["console"],
            "level": LOG_LEVEL,  # Use configured log level for task-specific logs
            "propagate": False,
        },
        "celery.worker": {
            "handlers": ["console"],
            "level": LOG_LEVEL,  # Use configured log level for worker logs
            "propagate": False,
        },
        "celery.beat": {
            "handlers": ["console"],
            "level": LOG_LEVEL,  # Use configured log level for scheduler logs
            "propagate": False,
        },
        # Add any other loggers you need to capture TRACE logs from
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,  # Use user-configured level instead of hardcoded 'INFO'
    },
}

# Connect script execution safety settings
# Allowed base directories for custom scripts; real paths must be inside
_allowed_dirs_env = os.environ.get("DISPATCHARR_ALLOWED_SCRIPT_DIRS", "/data/scripts")
CONNECT_ALLOWED_SCRIPT_DIRS = [p for p in _allowed_dirs_env.split(":") if p]

# Max execution time (seconds) for scripts
CONNECT_SCRIPT_TIMEOUT = int(os.environ.get("DISPATCHARR_SCRIPT_TIMEOUT", "10"))

# Truncate stdout/stderr to this many characters to avoid large outputs
CONNECT_SCRIPT_MAX_OUTPUT = int(os.environ.get("DISPATCHARR_SCRIPT_MAX_OUTPUT", "65536"))

# Require executable bit and disallow world-writable files
CONNECT_SCRIPT_REQUIRE_EXECUTABLE = True
CONNECT_SCRIPT_DISALLOW_WORLD_WRITABLE = True
