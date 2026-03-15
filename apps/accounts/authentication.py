import asyncio
from concurrent.futures import ThreadPoolExecutor

from rest_framework import authentication
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import (
    JWTAuthentication as BaseJWTAuthentication,
)
from django.conf import settings
from .models import User


_sync_executor = ThreadPoolExecutor(max_workers=4)


def _ensure_sync(func, *args, **kwargs):
    """
    Ensure a function with database access runs in a synchronous context.

    When running under an ASGI server (e.g. Daphne), Django may detect that
    the current thread has a running event loop, causing ORM calls to raise
    SynchronousOnlyOperation.  This helper detects that situation and
    re-executes the callable in a plain worker thread where no event loop
    is present.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running event loop – safe to call directly.
        return func(*args, **kwargs)

    # Running inside an async context – execute in a separate thread.
    return _sync_executor.submit(func, *args, **kwargs).result()


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
