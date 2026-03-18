from rest_framework import authentication
from rest_framework import exceptions
from django.conf import settings
from .models import User


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
            user = User.objects.get(api_key=raw_key)
        except User.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid API key")

        if not user.is_active:
            raise exceptions.AuthenticationFailed("User inactive")

        return (user, None)

    def authenticate_header(self, request):
        return self.keyword
