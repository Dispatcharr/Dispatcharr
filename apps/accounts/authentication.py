from rest_framework import authentication
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import (
    JWTAuthentication as BaseJWTAuthentication,
)
from django.conf import settings
from .models import User
from dispatcharr.utils import ensure_sync


def _ensure_sync(func, *args, **kwargs):
    """Thin wrapper kept for backward compatibility; delegates to ensure_sync."""
    return ensure_sync(func, *args, **kwargs)


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
