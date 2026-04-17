from rest_framework import authentication
from rest_framework import exceptions
from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from .models import User


class JWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "rest_framework_simplejwt.authentication.JWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "JWT Bearer authentication.\n\n"
                "Obtain a token pair via `POST /api/accounts/token/` using your username and password, "
                "then paste the **access token** here — Swagger adds the `Bearer ` prefix automatically.\n\n"
                "Access tokens expire after 30 minutes. Refresh using `POST /api/accounts/token/refresh/`."
            ),
        }


class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.ApiKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": (
                "API key authentication.\n\n"
                "Pass your personal API key in the `X-API-Key` request header. "
                "Keys can be generated via `POST /api/accounts/api-keys/generate/` "
                "and revoked via `POST /api/accounts/api-keys/revoke/`."
            ),
        }


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
