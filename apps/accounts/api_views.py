from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import Group, Permission
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework import viewsets, status
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
import json
from .permissions import IsAdmin, Authenticated
from dispatcharr.utils import network_access_allowed

from .models import User
from .serializers import UserSerializer, GroupSerializer, PermissionSerializer
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


class TokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        # Custom logic here
        if not network_access_allowed(request, "UI"):
            # Log blocked login attempt due to network restrictions
            from core.utils import log_system_event
            username = request.data.get("username", 'unknown')
            client_ip = request.META.get('REMOTE_ADDR', 'unknown')
            user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
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
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')

        try:
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
            raise  # Re-raise the exception to maintain normal error flow


class TokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        # Custom logic here
        if not network_access_allowed(request, "UI"):
            # Log blocked token refresh attempt due to network restrictions
            from core.utils import log_system_event
            client_ip = request.META.get('REMOTE_ADDR', 'unknown')
            user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
            log_system_event(
                event_type='login_failed',
                user='token_refresh',
                client_ip=client_ip,
                user_agent=user_agent,
                reason='Network access denied (token refresh)',
            )
            return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)

        return super().post(request, *args, **kwargs)


@csrf_exempt  # In production, consider CSRF protection strategies or ensure this endpoint is only accessible when no superuser exists.
def initialize_superuser(request):
    # If a superuser already exists, always indicate that
    if User.objects.filter(is_superuser=True).exists():
        return JsonResponse({"superuser_exists": True})

    if request.method == "POST":
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
    # For GET requests, indicate no superuser exists
    return JsonResponse({"superuser_exists": False})


# 🔹 1) Authentication APIs
class AuthViewSet(viewsets.ViewSet):
    """Handles user login and logout"""

    def get_permissions(self):
        """
        Login doesn't require auth, but logout does
        """
        if self.action == 'logout':
            from rest_framework.permissions import IsAuthenticated
            return [IsAuthenticated()]
        return []

    @swagger_auto_schema(
        operation_description="Authenticate and log in a user",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["username", "password"],
            properties={
                "username": openapi.Schema(type=openapi.TYPE_STRING),
                "password": openapi.Schema(
                    type=openapi.TYPE_STRING, format=openapi.FORMAT_PASSWORD
                ),
            },
        ),
        responses={200: "Login successful", 400: "Invalid credentials"},
    )
    def login(self, request):
        """Logs in a user and returns user details"""
        username = request.data.get("username")
        password = request.data.get("password")
        user = authenticate(request, username=username, password=password)

        # Get client info for logging
        from core.utils import log_system_event
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')

        if user:
            login(request, user)
            # Update last_login timestamp
            from django.utils import timezone
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])

            # Log successful login
            log_system_event(
                event_type='login_success',
                user=username,
                client_ip=client_ip,
                user_agent=user_agent,
            )

            return Response(
                {
                    "message": "Login successful",
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "groups": list(user.groups.values_list("name", flat=True)),
                    },
                }
            )

        # Log failed login attempt
        log_system_event(
            event_type='login_failed',
            user=username or 'unknown',
            client_ip=client_ip,
            user_agent=user_agent,
            reason='Invalid credentials',
        )
        return Response({"error": "Invalid credentials"}, status=400)

    @swagger_auto_schema(
        operation_description="Log out the current user",
        responses={200: "Logout successful"},
    )
    def logout(self, request):
        """Logs out the authenticated user"""
        # Log logout event before actually logging out
        from core.utils import log_system_event
        username = request.user.username if request.user and request.user.is_authenticated else 'unknown'
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')

        log_system_event(
            event_type='logout',
            user=username,
            client_ip=client_ip,
            user_agent=user_agent,
        )

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

    @swagger_auto_schema(
        operation_description="Retrieve a list of users",
        responses={200: UserSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description="Retrieve a specific user by ID")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_description="Create a new user")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(operation_description="Update a user")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(operation_description="Delete a user")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @swagger_auto_schema(
        method="get",
        operation_description="Get active user information",
    )
    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        user = request.user
        serializer = UserSerializer(user)
        return Response(serializer.data)


# 🔹 3) Group Management APIs
class GroupViewSet(viewsets.ModelViewSet):
    """Handles CRUD operations for Groups"""

    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [Authenticated]

    @swagger_auto_schema(
        operation_description="Retrieve a list of groups",
        responses={200: GroupSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(operation_description="Retrieve a specific group by ID")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(operation_description="Create a new group")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(operation_description="Update a group")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(operation_description="Delete a group")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


# 🔹 4) Permissions List API
@swagger_auto_schema(
    method="get",
    operation_description="Retrieve a list of all permissions",
    responses={200: PermissionSerializer(many=True)},
)
@api_view(["GET"])
@permission_classes([Authenticated])
def list_permissions(request):
    """Returns a list of all available permissions"""
    permissions = Permission.objects.all()
    serializer = PermissionSerializer(permissions, many=True)
    return Response(serializer.data)
