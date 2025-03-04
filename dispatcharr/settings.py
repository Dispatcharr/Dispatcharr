import os
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'REPLACE_ME_WITH_A_REAL_SECRET'
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")

DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    'apps.api',
    'apps.accounts',
    'apps.channels',
    'apps.dashboard',
    'apps.epg',
    'apps.hdhr',
    'apps.m3u',
    'apps.output',
    'core',
    'drf_yasg',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
]



MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'corsheaders.middleware.CorsMiddleware',
]


ROOT_URLCONF = 'dispatcharr.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'frontend/build'),
            BASE_DIR / "templates"
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = 'dispatcharr.wsgi.application'
ASGI_APPLICATION = 'dispatcharr.asgi.application'

if os.getenv('DB_ENGINE', None) == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': '/data/dispatcharr.db',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('POSTGRES_DB', 'dispatcharr'),
            'USER': os.environ.get('POSTGRES_USER', 'dispatch'),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'secret'),
            'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
            'PORT': int(os.environ.get('POSTGRES_PORT', 5432)),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
]

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'rest_framework.schemas.coreapi.AutoSchema',
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
}

SWAGGER_SETTINGS = {
   'SECURITY_DEFINITIONS': {
      'Bearer': {
            'type': 'apiKey',
            'name': 'Authorization',
            'in': 'header'
      }
   }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'static'  # Directory where static files will be collected

# Adjust STATICFILES_DIRS to include the paths to the directories that contain your static files.
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'frontend/build/static'),  # React build static files
]


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'accounts.User'

CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_URL = '/media/'


SERVER_IP = "127.0.0.1"

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = ['*']
APPEND_SLASH = True

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': False,  # Optional: Whether to rotate refresh tokens
    'BLACKLIST_AFTER_ROTATION': True,  # Optional: Whether to blacklist refresh tokens
}
