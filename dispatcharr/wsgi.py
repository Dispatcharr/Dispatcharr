"""
WSGI config for dispatcharr project.
"""
# When running under uWSGI with gevent, ensure monkey-patching is fully
# applied before any other imports.  Django's setup triggers the import of
# dispatcharr/__init__.py → celery.py, which initialises the Celery broker
# transport.  If those imports happen before sockets are patched, Celery's
# Redis connection pool holds unpatched sockets that silently fail under
# gevent's cooperative scheduling.  Calling patch_all() here—before the
# Django import chain—guarantees every socket (including pooled broker
# connections) is gevent-aware.  The call is idempotent, so it's harmless
# if uWSGI's gevent plugin has already patched.
try:
    from gevent import monkey
    monkey.patch_all()
except ImportError:
    pass

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
application = get_wsgi_application()
