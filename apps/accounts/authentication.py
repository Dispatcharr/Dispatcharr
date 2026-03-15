import asyncio
import os
import threading

from rest_framework import authentication
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import (
    JWTAuthentication as BaseJWTAuthentication,
)
from django.conf import settings
from .models import User


def _ensure_sync(func, *args, **kwargs):
    """
    Ensure a function with database access runs in a synchronous context.

    When running under an ASGI server (e.g. Daphne) or a gevent-based WSGI
    server, Django may detect that the current thread has a running event
    loop, causing ORM calls to raise ``SynchronousOnlyOperation``.

    This helper detects that situation and re-executes the callable in a
    dedicated worker thread.  ``DJANGO_ALLOW_ASYNC_UNSAFE`` is set inside
    the worker so that Django's ``@async_unsafe`` guard on the database
    cursor is bypassed – the call is genuinely synchronous and isolated
    from the event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running event loop – safe to call directly.
        return func(*args, **kwargs)

    # Running inside an async context – execute in an isolated thread.
    result = [None]
    exception = [None]

    def _worker():
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        try:
            result[0] = func(*args, **kwargs)
        except BaseException as e:
            exception[0] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()

    if exception[0] is not None:
        raise exception[0]
    return result[0]


class JWTAuthentication(BaseJWTAuthentication):
    """
    Async-safe JWT authentication.

    Overrides ``get_user`` so the database lookup is performed in a
    synchronous context even when the ASGI server dispatches the request
    inside an async event loop.
    """

    def get_user(self, validated_token):
        return _ensure_sync(super().get_user, validated_token)


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """
    Accepts header `Authorization: ApiKey <key>` or `X-API-Key: <key>`.
    """

    keyword = "ApiKey"

    def authenticate(self, request):
        # Check X-API-Key header first
        raw_key = request.META.get("HTTP_X_API_KEY")

        if not raw_key:
            auth = authentication.get_authorization_header(request).split()
            if not auth:
                return None

            if len(auth) != 2:
                return None

            scheme = auth[0].decode().lower()
            if scheme != self.keyword.lower():
                return None

            raw_key = auth[1].decode()

        if not raw_key:
            return None

        if not raw_key:
            return None

        try:
            user = _ensure_sync(User.objects.get, api_key=raw_key)
        except User.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid API key")

        if not user.is_active:
            raise exceptions.AuthenticationFailed("User inactive")

        return (user, None)

    def authenticate_header(self, request):
        return self.keyword
