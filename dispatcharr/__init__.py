# dispatcharr/__init__.py

# For Celery: import eagerly so @shared_task binds to the configured app.
# Lazy-loading via __getattr__ left the default Celery app unconfigured in
# production (no CELERY_BROKER_URL in env), so .delay() fell back to AMQP
# localhost and failed with ConnectionRefusedError.
from .celery import app as celery_app

__all__ = ("celery_app",)
