"""
WSGI config for dispatcharr project.
"""
from gevent_patch import patch_if_needed
patch_if_needed()

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
application = get_wsgi_application()
