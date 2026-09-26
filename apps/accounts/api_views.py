from django.contrib.auth import authenticate, login, logout
import logging
from django.contrib.auth.models import Group, Permission
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework import viewsets, status, serializers
from rest_framework.parsers import JSONParser
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, inline_serializer
from drf_spectacular.types import OpenApiTypes
import json
import secrets
from .app_data import (
    APP_DATA_MAX_CONTENT_LENGTH,
    CODE_BODY_TOO_LARGE,
    CODE_FORBIDDEN,
    CODE_INVALID_CONTENT_LENGTH,
    CODE_KEY_NOT_FOUND,
    CODE_USER_NOT_FOUND,
    CODE_VALUE_TOO_DEEP,
    AppDataError,
    app_data_error_body,
    clear_user_app_data,
    delete_app_data_key,
    get_app_data_value,
    put_app_data_value,
    summarize_user_app_data,
    validate_app_data_key,
    validate_app_data_value,
)
from .permissions import IsAdmin, Authenticated
from .throttling import (
    LoginRateThrottle,
    emit_login_rate_limit_lockout,
    enforce_login_rate_limit,
)
from dispatcharr.utils import (
    SETUP_ALLOWED_IP_ENV,
    get_client_ip,
    network_access_allowed,
    proxy_auth_identity,
    setup_ip_allowed,
)

from .models import User
from .serializers import (
    UserSerializer,
    GroupSerializer,
    PermissionSerializer,
    ProxyLoginResponseSerializer,
    AppDataListResponseSerializer,
    AppDataDetailErrorSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

logger = logging.getLogger(__name__)


def _setup_status_payload(request, *, superuser_exists):
    """Build initialize-superuser JSON including client IP / setup gate info."""
    payload = {"superuser_exists": superuser_exists}
    if superuser_exists:
        return payload

    allowed, client_ip = setup_ip_allowed(request)
    payload["client_ip"] = client_ip
    payload["setup_allowed"] = allowed
    return payload


def _setup_forbidden_response(client_ip):
    return JsonResponse(
        {
            "error": (
                "Web setup is limited to local networks by default. "
                f"Set {SETUP_ALLOWED_IP_ENV} to your IP to allow setup from this "
                "network, or create the account with: python manage.py createsuperuser"
            ),
            "client_ip": client_ip,
            "setup_allowed": False,
        },
        status=403,
    )


def _resolve_proxy_auth_user(identity):
    """Match a proxy-asserted identity by username, then by unambiguous email.

    Case-insensitive matches must be unique. With case-distinct accounts
    ("Admin" and "admin") an iexact lookup could otherwise return either one,
    so only an exact username or a single case-insensitive match resolves.
    """
    exact = User.objects.filter(username=identity).first()
    if exact is not None:
        return exact

    matches = list(User.objects.filter(username__iexact=identity)[:2])
    if matches:
        return matches[0] if len(matches) == 1 else None

    if "@" in identity:
        matches = list(User.objects.filter(email__iexact=identity)[:2])
        if len(matches) == 1:
            return matches[0]

    return None


class TokenObtainPairView(TokenObtainPairView):
    throttle_classes = [LoginRateThrottle]

    def throttled(self, request, wait):
        emit_login_rate_limit_lockout(request, wait=wait)
        return super().throttled(request, wait)

    def post(self, request, *args, **kwargs):
        if not network_access_allowed(request, "UI"):
            # Log blocked login attempt due to network restrictions
            from core.utils import log_system_event
            username = request.data.get("username", 'unknown')
            client_ip = get_client_ip(request) or "unknown"
            user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
            logger.info(f"Login blocked by network policy: user={username} ip={client_ip} ua={user_agent}")
            log_system_event(
                event_type='login_failed',
                user=username,
                client_ip=client_ip,
                user_agent=user_agent,
                reason='Network access denied',
            )
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # Get the response from the parent class first
        username = request.data.get("username")

        # Log login attempt
        from core.utils import log_system_event
        client_ip = get_client_ip(request) or "unknown"
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')

        try:
            logger.debug(f"Attempting JWT login for user={username}")
            response = super().post(request, *args, **kwargs)

            # If login was successful, update last_login and log success
            if response.status_code == 200:
                if username:
                    from django.utils import timezone
                    try:
                        user = User.objects.get(username=username)
                        user.last_login = timezone.now()
                        user.save(update_fields=['last_login'])

                        # Log successful login
                        log_system_event(
                            event_type='login_success',
                            user=username,
                            client_ip=client_ip,
                            user_agent=user_agent,
                        )
                        logger.info(f"Login success: user={username} ip={client_ip}")
                    except User.DoesNotExist:
                        pass  # User doesn't exist, but login somehow succeeded
            else:
                # Log failed login attempt
                log_system_event(
                    event_type='login_failed',
                    user=username or 'unknown',
                    client_ip=client_ip,
                    user_agent=user_agent,
                    reason='Invalid credentials',
                )
                logger.info(f"Login failed: user={username} ip={client_ip}")

            return response

        except Exception as e:
            # If parent class raises an exception (e.g., validation error), log failed attempt
            log_system_event(
                event_type='login_failed',
                user=username or 'unknown',
                client_ip=client_ip,
                user_agent=user_agent,
                reason=f'Authentication error: {str(e)[:100]}',
            )
            logger.error(f"Login error for user={username}: {e}")
            raise  # Re-raise the exception to maintain normal error flow


class TokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        # Custom logic here
        if not network_access_allowed(request, "UI"):
            # Log blocked token refresh attempt due to network restrictions
            from core.utils import log_system_event
            client_ip = get_client_ip(request) or "unknown"
            user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
            logger.info(f"Token refresh blocked by network policy: ip={client_ip} ua={user_agent}")
            log_system_event(
                event_type='login_failed',
                user='token_refresh',
                client_ip=client_ip,
                user_agent=user_agent,
                reason='Network access denied (token refresh)',
            )
            return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)

        return super().post(request, *args, **kwargs)


@csrf_exempt  # Bootstrap only; POST is IP-gated and closes once an admin exists.
def initialize_superuser(request):
    # If an admin-level user already exists, the system is configured
    if User.objects.filter(user_level__gte=10).exists():
        return JsonResponse(_setup_status_payload(request, superuser_exists=True))

    if request.method == "POST":
        allowed, client_ip = setup_ip_allowed(request)
        if not allowed:
            logger.info(
                "initialize-superuser POST blocked by setup IP policy: ip=%s",
                client_ip,
            )
            return _setup_forbidden_response(client_ip)

        try:
            data = json.loads(request.body)
            username = data.get("username")
            password = data.get("password")
            email = data.get("email", "")
            if not username or not password:
                return JsonResponse(
                    {"error": "Username and password are required."}, status=400
                )
            # Create the superuser
            User.objects.create_superuser(
                username=username, password=password, email=email, user_level=10
            )
            return JsonResponse({"superuser_exists": True})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    # GET: no admin yet. Include client IP so the UI can help remote / VPS setups.
    return JsonResponse(_setup_status_payload(request, superuser_exists=False))


# 🔹 1) Authentication APIs
class AuthViewSet(viewsets.ViewSet):
    """Handles user login and logout"""

    def get_permissions(self):
        """
        Login doesn't require auth, but logout does
        """
        if self.action == 'logout':
            return [Authenticated()]
        return []

    @extend_schema(
        description="Alias for POST /api/accounts/token/ — returns JWT access and refresh tokens.",
        request=inline_serializer(
            name="LoginRequest",
            fields={
                "username": serializers.CharField(),
                "password": serializers.CharField(),
            },
        ),
    )
    def login(self, request):
        """Delegates to TokenObtainPairView (JWT login). Throttling, logging, and
        network access checks are handled there."""
        view = TokenObtainPairView.as_view()
        return view(request._request)

    @extend_schema(
        description=(
            "Exchange a reverse-proxy-asserted identity for JWT tokens. "
            "Returns 401 unless reverse proxy auth is enabled, the request "
            "carries the configured header, and the connecting peer is a "
            "trusted proxy. Takes no request body."
        ),
        request=None,
        responses={200: ProxyLoginResponseSerializer},
    )
    def proxy_login(self, request):
        """Sign in the user named by the trusted proxy's header."""
        from core.utils import log_system_event

        client_ip = get_client_ip(request) or "unknown"
        user_agent = request.META.get("HTTP_USER_AGENT", "unknown")

        if not network_access_allowed(request, "UI"):
            logger.info(f"Proxy login blocked by network policy: ip={client_ip}")
            log_system_event(
                event_type="login_failed",
                user="proxy_auth",
                client_ip=client_ip,
                user_agent=user_agent,
                reason="Network access denied",
            )
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        identity = proxy_auth_identity(request)
        if not identity:
            return Response(
                {"detail": "Reverse proxy authentication unavailable."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Shares the `login` budget with password and admin sign-in. Checked
        # here rather than as a view throttle so the web UI's availability
        # probe, which returns above without minting anything, does not spend
        # login attempts the user needs for the password form.
        throttled = enforce_login_rate_limit(request, username=identity)
        if throttled is not None:
            logger.info(f"Proxy login throttled: identity={identity} ip={client_ip}")
            response = Response(
                {"detail": "Too many login attempts. Try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            retry_after = throttled.get("Retry-After")
            if retry_after:
                response["Retry-After"] = retry_after
            return response

        user = _resolve_proxy_auth_user(identity)
        if user is None or not user.is_active:
            reason = (
                "No matching account"
                if user is None
                else "Account inactive"
            )
            logger.info(
                f"Proxy login rejected: identity={identity} ip={client_ip} ({reason})"
            )
            log_system_event(
                event_type="login_failed",
                user=identity,
                client_ip=client_ip,
                user_agent=user_agent,
                reason=f"Reverse proxy auth: {reason.lower()}",
            )
            return Response(
                {"detail": "No account matches the authenticated identity."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        from django.utils import timezone

        refresh = RefreshToken.for_user(user)
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        log_system_event(
            event_type="login_success",
            user=user.username,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        logger.info(f"Proxy login success: user={user.username} ip={client_ip}")

        serializer = ProxyLoginResponseSerializer(
            {"access": str(refresh.access_token), "refresh": str(refresh)}
        )
        return Response(serializer.data)

    @extend_schema(
        description="Log out the current user",
    )
    def logout(self, request):
        """Logs out the authenticated user"""
        # Log logout event before actually logging out
        from core.utils import log_system_event
        username = request.user.username if request.user and request.user.is_authenticated else 'unknown'
        client_ip = get_client_ip(request) or "unknown"
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')

        log_system_event(
            event_type='logout',
            user=username,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        logger.info(f"Logout: user={username} ip={client_ip}")

        logout(request)
        return Response({"message": "Logout successful"})


# 🔹 2) User Management APIs
class UserViewSet(viewsets.ModelViewSet):
    """Handles CRUD operations for Users"""

    queryset = User.objects.all().prefetch_related('channel_profiles')
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action == "me":
            return [Authenticated()]

        return [IsAdmin()]

    @extend_schema(
        description="Retrieve a list of users",
        responses={200: UserSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(description="Retrieve a specific user by ID")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(description="Create a new user")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(description="Update a user")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(description="Delete a user")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        description="Get or update active user information. PATCH updates custom_properties with merge semantics.",
        methods=["GET", "PATCH"],
    )
    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        user = request.user
        if request.method == "PATCH":
            ALLOWED_FIELDS = {"custom_properties", "first_name", "last_name", "email", "password"}
            disallowed = set(request.data.keys()) - ALLOWED_FIELDS

            for key in disallowed:
                request.data.pop(key, None)

            # Strip admin-managed keys from custom_properties so users cannot
            # set their own XC credentials, network rules, or catchup/VOD
            # access via this endpoint.
            ADMIN_ONLY_PROPS = {
                "xc_password",
                "allowed_networks",
                "catchup_enabled",
                "vod_movies_enabled",
                "vod_series_enabled",
                "dvr_access",
                "xc_live_refresh_on_request",
                "xc_live_refresh_wait_for_completion",
                "xc_live_refresh_wait_timeout_seconds",
                "allowed_m3u_profile_ids",
            }
            cp = request.data.get("custom_properties")
            if isinstance(cp, dict):
                for key in ADMIN_ONLY_PROPS:
                    cp.pop(key, None)

            serializer = UserSerializer(user, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        serializer = UserSerializer(user)
        return Response(serializer.data)


# 🔹 3) Group Management APIs (Django auth.Group; unused by the React UI)
class GroupViewSet(viewsets.ModelViewSet):
    """CRUD for Django auth groups and their permissions.

    Dispatcharr authorization uses ``user_level``, not these groups. The
    endpoint is kept for compatibility but restricted to admins so
    non-admins cannot invent auth groups or attach Django permissions.
    """

    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [IsAdmin]

    @extend_schema(
        description="Retrieve a list of groups",
        responses={200: GroupSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(description="Retrieve a specific group by ID")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(description="Create a new group")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(description="Update a group")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(description="Delete a group")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


# API Key management
class APIKeyViewSet(viewsets.ViewSet):
    permission_classes = [Authenticated]

    def list(self, request):
        user = request.user
        return Response({"key": user.api_key})

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        target_user = request.user
        user_id = request.data.get("user_id")

        if user_id:
            from .permissions import IsAdmin

            if not IsAdmin().has_permission(request, self):
                return Response({"detail": "Not allowed to create keys for other users."}, status=status.HTTP_403_FORBIDDEN)

            try:
                target_user = User.objects.get(id=int(user_id))
            except Exception:
                return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        raw = secrets.token_urlsafe(40)
        target_user.api_key = raw
        target_user.save(update_fields=["api_key"])

        user_data = UserSerializer(target_user).data
        return Response({"key": raw, "user": user_data}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="revoke")
    def revoke(self, request):
        target_user = request.user
        user_id = request.data.get("user_id")

        if user_id:
            from .permissions import IsAdmin

            if not IsAdmin().has_permission(request, self):
                return Response({"detail": "Not allowed to revoke keys for other users."}, status=status.HTTP_403_FORBIDDEN)

            try:
                target_user = User.objects.get(id=int(user_id))
            except Exception:
                return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        target_user.api_key = None
        target_user.save(update_fields=["api_key"])

        return Response({"success": True})


class UserAppDataMixin:
    """Shared auth helpers for per-app user JSON (one DB row per key).

    Keys are namespaces chosen by the client app (not secrets). Any credential
    for that user can read every key. Values are replace-only PUT of a JSON
    object, size-capped so a glitchy client cannot bloat the database.
    """

    permission_classes = [Authenticated]
    # JSON only. A form or multipart body would arrive as a QueryDict and be
    # stored as lists of strings, which is never what an app meant to save.
    parser_classes = [JSONParser]

    def _resolve_target_user(self, request, user_id=None):
        if user_id is None:
            return request.user
        if request.user.pk == user_id:
            return request.user
        if not IsAdmin().has_permission(request, self):
            return Response(
                app_data_error_body(
                    "Not allowed to access app data for other users.",
                    CODE_FORBIDDEN,
                ),
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(
                app_data_error_body("User not found.", CODE_USER_NOT_FOUND),
                status=status.HTTP_404_NOT_FOUND,
            )

    def _app_data_error_response(self, exc):
        return Response(exc.as_response_data(), status=exc.status_code)

    def _user_not_found_response(self):
        return Response(
            app_data_error_body("User not found.", CODE_USER_NOT_FOUND),
            status=status.HTTP_404_NOT_FOUND,
        )

    def _reject_oversized_body(self, request):
        raw = request.META.get("CONTENT_LENGTH")
        if raw in (None, ""):
            # Safe to let through: DRF treats a missing length as an empty body
            # and never reads the stream, so nothing large can be parsed.
            return None
        try:
            content_length = int(raw)
        except (TypeError, ValueError):
            return Response(
                app_data_error_body(
                    "Invalid Content-Length header.",
                    CODE_INVALID_CONTENT_LENGTH,
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )
        if content_length < 0:
            return Response(
                app_data_error_body(
                    "Invalid Content-Length header.",
                    CODE_INVALID_CONTENT_LENGTH,
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )
        if content_length > APP_DATA_MAX_CONTENT_LENGTH:
            return Response(
                app_data_error_body(
                    (
                        f"Request body exceeds maximum of "
                        f"{APP_DATA_MAX_CONTENT_LENGTH} bytes."
                    ),
                    CODE_BODY_TOO_LARGE,
                ),
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        return None


_APP_DATA_KEY_PARAM = OpenApiParameter(
    name="key",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    required=True,
    description=(
        "App namespace: 8 to 64 characters matching "
        "[A-Za-z0-9][A-Za-z0-9._-]* (must start with a letter or digit). "
        "A typical reverse-DNS style key is fine, for example "
        "com.example.tvremote. Keys are namespaces, not secrets."
    ),
)


class UserAppDataCollectionView(UserAppDataMixin, APIView):
    """List keys/sizes or clear all app data for a user (no values, no PUT)."""

    @extend_schema(
        summary="List app data keys",
        description=(
            "Return the app namespaces stored for the user with per-key byte "
            "sizes and the current limits. Values are never included.\n\n"
            "Use `/api/accounts/users/me/app-data/` for the authenticated user "
            "(including streamers), or `/api/accounts/users/{user_id}/app-data/` "
            "as an admin for another user (owners may also use their own id).\n\n"
            "Caps: 128 KiB per app, 1 MiB and 25 apps per user, nesting depth 8."
        ),
        responses={
            200: AppDataListResponseSerializer,
            403: AppDataDetailErrorSerializer,
            404: AppDataDetailErrorSerializer,
        },
    )
    def get(self, request, user_id=None):
        target = self._resolve_target_user(request, user_id=user_id)
        if isinstance(target, Response):
            return target
        return Response(summarize_user_app_data(target.pk))

    @extend_schema(
        summary="Clear all app data",
        description=(
            "Delete every app namespace stored for the user. Idempotent when "
            "nothing is stored. Owner or admin only."
        ),
        responses={
            204: OpenApiTypes.NONE,
            403: AppDataDetailErrorSerializer,
            404: AppDataDetailErrorSerializer,
        },
    )
    def delete(self, request, user_id=None):
        target = self._resolve_target_user(request, user_id=user_id)
        if isinstance(target, Response):
            return target

        clear_user_app_data(target.pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserAppDataKeyView(UserAppDataMixin, APIView):
    """Get, replace, or clear one app's JSON object under a key."""

    @extend_schema(
        summary="Get one app's stored JSON object",
        description=(
            "Return the JSON object stored under the given app key. "
            "Owner or admin only. Missing keys return 404 with "
            "`code=key_not_found`."
        ),
        parameters=[_APP_DATA_KEY_PARAM],
        responses={
            200: OpenApiTypes.OBJECT,
            400: AppDataDetailErrorSerializer,
            403: AppDataDetailErrorSerializer,
            404: AppDataDetailErrorSerializer,
        },
    )
    def get(self, request, key, user_id=None):
        target = self._resolve_target_user(request, user_id=user_id)
        if isinstance(target, Response):
            return target

        try:
            validate_app_data_key(key)
        except AppDataError as exc:
            return self._app_data_error_response(exc)
        value = get_app_data_value(target.pk, key)
        if value is None:
            return Response(
                app_data_error_body(
                    "App data not found for this key.",
                    CODE_KEY_NOT_FOUND,
                ),
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(value)

    @extend_schema(
        summary="Replace one app's stored JSON object",
        description=(
            "Replace the JSON object stored under the given app key. "
            "Request body must be a JSON object (not an array or scalar). "
            "Caps: 128 KiB per app, 1 MiB and 25 apps per user, nesting "
            "depth 8. Owner or admin only.\n\n"
            "Error `code` values include `value_too_large` (413), "
            "`total_too_large` (413), `max_apps` (409), `key_invalid` (400), "
            "and `value_not_object` (400)."
        ),
        parameters=[_APP_DATA_KEY_PARAM],
        request=OpenApiTypes.OBJECT,
        responses={
            200: OpenApiTypes.OBJECT,
            400: AppDataDetailErrorSerializer,
            403: AppDataDetailErrorSerializer,
            404: AppDataDetailErrorSerializer,
            409: AppDataDetailErrorSerializer,
            413: AppDataDetailErrorSerializer,
        },
    )
    def put(self, request, key, user_id=None):
        oversized = self._reject_oversized_body(request)
        if oversized is not None:
            return oversized

        target = self._resolve_target_user(request, user_id=user_id)
        if isinstance(target, Response):
            return target

        try:
            validate_app_data_key(key)
            try:
                value = request.data
            except RecursionError:
                # The JSON parser itself gave up on absurdly nested input.
                raise AppDataError(
                    "App data value is nested too deeply",
                    code=CODE_VALUE_TOO_DEEP,
                )
            new_size = validate_app_data_value(value)
            put_app_data_value(target.pk, key, value, new_size)
        except AppDataError as exc:
            return self._app_data_error_response(exc)
        except User.DoesNotExist:
            return self._user_not_found_response()

        return Response(value)

    @extend_schema(
        summary="Clear one app's stored JSON object",
        description=(
            "Delete the JSON object stored under the given app key. "
            "Idempotent: a missing key still returns 204 (not 404). "
            "404 with `code=user_not_found` is only for an unknown "
            "`user_id` on the admin path. Owner or admin only."
        ),
        parameters=[_APP_DATA_KEY_PARAM],
        responses={
            204: OpenApiTypes.NONE,
            400: AppDataDetailErrorSerializer,
            403: AppDataDetailErrorSerializer,
            404: AppDataDetailErrorSerializer,
        },
    )
    def delete(self, request, key, user_id=None):
        target = self._resolve_target_user(request, user_id=user_id)
        if isinstance(target, Response):
            return target

        try:
            validate_app_data_key(key)
        except AppDataError as exc:
            return self._app_data_error_response(exc)

        delete_app_data_key(target.pk, key)
        return Response(status=status.HTTP_204_NO_CONTENT)


# 🔹 4) Permissions List API
@extend_schema(
    description="Retrieve a list of all permissions",
    responses={200: PermissionSerializer(many=True)},
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def list_permissions(request):
    """Returns a list of all available Django permissions (admin only)."""
    permissions = Permission.objects.all()
    serializer = PermissionSerializer(permissions, many=True)
    return Response(serializer.data)
