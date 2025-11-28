import os
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "REPLACE_ME_WITH_A_REAL_SECRET"
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_DB = os.environ.get("REDIS_DB", "0")

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
    "apps.channels.apps.ChannelsConfig",
    "apps.dashboard",
    "apps.epg",
    "apps.hdhr",
    "apps.m3u",
    "apps.output",
    "apps.proxy.apps.ProxyConfig",
    "apps.proxy.ts_proxy",
    "apps.vod.apps.VODConfig",
    "core",
    "daphne",
    "drf_yasg",
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

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [(REDIS_HOST, 6379, REDIS_DB)],  # Ensure Redis is running
        },
    },
}

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

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
]

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "rest_framework.schemas.coreapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
}

SWAGGER_SETTINGS = {
    "SECURITY_DEFINITIONS": {
        "Bearer": {"type": "apiKey", "name": "Authorization", "in": "header"}
    }
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

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

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
}

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"


SERVER_IP = "127.0.0.1"

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = ["http://*", "https://*"]
APPEND_SLASH = True

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": False,  # Optional: Whether to rotate refresh tokens
    "BLACKLIST_AFTER_ROTATION": True,  # Optional: Whether to blacklist refresh tokens
}

# Redis connection settings
REDIS_URL = "redis://localhost:6379/0"
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
