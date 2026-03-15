"""
dispatcharr/middleware.py

Provides middleware that ensures Django ORM calls can be made safely from
within an async event-loop context (Daphne/ASGI or gevent-patched asyncio).
"""
import os

from dispatcharr.utils import _is_async_context


class EnsureSyncMiddleware:
    """
    Detect an async event-loop context on the first request and allow Django's
    ORM to be called from it for the lifetime of the process.

    When Dispatcharr runs under Daphne (ASGI) or a gevent-based server whose
    hub integrates with asyncio, Django's ``@async_unsafe`` guard on database
    cursor access will raise ``SynchronousOnlyOperation`` for every ORM call
    because the event loop appears to be running.  Setting the environment
    variable ``DJANGO_ALLOW_ASYNC_UNSAFE=true`` tells Django to skip that
    guard.

    This middleware performs the detection once (on the first request) and,
    if an event loop is detected, sets the variable for the process.  All
    subsequent requests – including those that reach the view before
    authentication runs – benefit automatically.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE") and _is_async_context():
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        return self.get_response(request)
