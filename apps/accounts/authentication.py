import logging

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication, exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from dispatcharr.utils import get_client_ip

from .models import User
from .throttling import (
    api_key_failed_auth_limited,
    record_api_key_failed_auth,
)

logger = logging.getLogger(__name__)


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


def _emit_api_key_auth_lockout(request, username):
    """Log the lockout trip and maybe refresh the cooldown inbox notice."""
    from core.utils import log_system_event, notify_api_key_auth_lockout_inbox

    client_ip = get_client_ip(request) or "unknown"
    user_agent = request.META.get("HTTP_USER_AGENT", "unknown")
    log_system_event(
        event_type="login_failed",
        user=username or "api_key",
        client_ip=client_ip,
        user_agent=user_agent,
        reason="API key rate limited",
    )
    logger.info(
        "API key auth rate limited: user=%s ip=%s",
        username or "api_key",
        client_ip,
    )
    try:
        notify_api_key_auth_lockout_inbox()
    except Exception:
        logger.exception("Failed to create API key auth lockout inbox notice")


def _api_key_credential_failure(request, username):
    """Record a failed API-key attempt; emit lockout when the budget trips."""
    crossed = record_api_key_failed_auth(request)
    if crossed:
        _emit_api_key_auth_lockout(request, username)


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """
    Accepts header `Authorization: ApiKey <key>` or `X-API-Key: <key>`.

    Failed attempts (unknown key, inactive user, or non-UTF-8 ApiKey value)
    are rate-limited per client IP (Redis scope ``api_key_auth``). Missing or
    non-ApiKey auth does not consume that budget.
    """

    keyword = "ApiKey"

    def _extract_api_key(self, request):
        """Return ``(raw_key, undecodable)``.

        ``undecodable`` is True when the client sent ``Authorization: ApiKey``
        with a non-UTF-8 value. That is a presented attempt, not a missing key.
        """
        raw_key = request.META.get("HTTP_X_API_KEY")
        if raw_key:
            return raw_key, False

        auth = authentication.get_authorization_header(request).split()
        if not auth or len(auth) != 2:
            return None, False

        try:
            scheme = auth[0].decode().lower()
        except UnicodeDecodeError:
            return None, False

        if scheme != self.keyword.lower():
            return None, False

        try:
            return auth[1].decode(), False
        except UnicodeDecodeError:
            return None, True

    def _reject_invalid_api_key(self, request):
        limited, wait = api_key_failed_auth_limited(request)
        if limited:
            raise exceptions.Throttled(
                wait=wait,
                detail="Too many API key attempts. Try again later.",
            )
        _api_key_credential_failure(request, username=None)
        raise exceptions.AuthenticationFailed("Invalid API key")

    def authenticate(self, request):
        raw_key, undecodable = self._extract_api_key(request)
        if undecodable:
            return self._reject_invalid_api_key(request)
        if not raw_key:
            return None

        limited, wait = api_key_failed_auth_limited(request)
        if limited:
            raise exceptions.Throttled(
                wait=wait,
                detail="Too many API key attempts. Try again later.",
            )

        try:
            user = User.objects.get(api_key=raw_key)
        except User.DoesNotExist:
            _api_key_credential_failure(request, username=None)
            raise exceptions.AuthenticationFailed("Invalid API key")

        if not user.is_active:
            _api_key_credential_failure(request, username=user.username)
            raise exceptions.AuthenticationFailed("User inactive")

        return (user, None)

    def authenticate_header(self, request):
        return self.keyword


class QueryParamJWTAuthentication(JWTAuthentication):
    """Reads a JWT from the `token` query parameter. Used for media endpoints
    where the browser cannot set Authorization headers (e.g. <video src>)."""

    def authenticate(self, request):
        params = getattr(request, "query_params", request.GET)
        raw_token = params.get("token")
        if not raw_token:
            return None
        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except (InvalidToken, TokenError):
            return None
