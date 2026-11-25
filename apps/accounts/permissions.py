from rest_framework.permissions import IsAuthenticated
from .models import User
from dispatcharr.utils import network_access_allowed


class Authenticated(IsAuthenticated):
    def has_permission(self, request, view):
        is_authenticated = super().has_permission(request, view)
        user = request.user if hasattr(request, 'user') and request.user.is_authenticated else None
        network_allowed = network_access_allowed(request, "UI", user)

        return is_authenticated and network_allowed


class IsStandardUser(Authenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False

        return request.user and request.user.user_level >= User.UserLevel.STANDARD


class IsAdmin(Authenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False

        return request.user.user_level >= 10


class IsAdminOrDVRManager(Authenticated):
    """Admin or a standard user with ``dvr_access=manage``."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        from apps.channels.dvr_access import is_dvr_manage_enabled

        return is_dvr_manage_enabled(user=request.user)


class IsDVRViewer(Authenticated):
    """Admin or a standard user with ``dvr_access`` of ``view`` or ``manage``."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        from apps.channels.dvr_access import is_dvr_view_enabled

        return is_dvr_view_enabled(user=request.user)


class IsOwnerOfObject(Authenticated):
    def has_object_permission(self, request, view, obj):
        if not super().has_permission(request, view):
            return False

        is_admin = IsAdmin().has_permission(request, view)
        is_owner = request.user in obj.users.all()

        return is_admin or is_owner


permission_classes_by_action = {
    "list": [IsStandardUser],
    "create": [IsAdmin],
    "retrieve": [IsStandardUser],
    "update": [IsAdmin],
    "partial_update": [IsAdmin],
    "destroy": [IsAdmin],
}

permission_classes_by_method = {
    "GET": [IsStandardUser],
    "POST": [IsAdmin],
    "PATCH": [IsAdmin],
    "PUT": [IsAdmin],
    "DELETE": [IsAdmin],
}


def _instantiate_permission_classes(permission_classes):
    return [perm() for perm in permission_classes]


def permissions_for_action(view, *, default=IsAdmin):
    """Resolve DRF permissions for the current viewset action.

    Order:
    1. ``permission_classes`` from ``@action(..., permission_classes=...)``
    2. Shared CRUD map ``permission_classes_by_action``
    3. Fail closed to ``default`` (``IsAdmin`` unless overridden)

    Call sites should keep intentional special cases (AllowAny media, DVR
    roles, admin allowlists) as explicit branches before calling this helper.
    """
    action = getattr(view, "action", None)
    if action:
        handler = getattr(view, action, None)
        action_kwargs = getattr(handler, "kwargs", None) if handler else None
        if action_kwargs and "permission_classes" in action_kwargs:
            return _instantiate_permission_classes(
                action_kwargs["permission_classes"]
            )

    if action in permission_classes_by_action:
        return _instantiate_permission_classes(
            permission_classes_by_action[action]
        )

    return [default()]


def permissions_for_method(request, *, default=IsAdmin):
    """Resolve DRF permissions for an APIView HTTP method.

    Uses ``permission_classes_by_method``. HEAD is authorized exactly like GET
    (Django serves HEAD from the GET handler), and any other unlisted method,
    such as OPTIONS, fails closed to ``default``.
    """
    method = getattr(request, "method", None)
    if method == "HEAD":
        method = "GET"
    if method in permission_classes_by_method:
        return _instantiate_permission_classes(
            permission_classes_by_method[method]
        )
    return [default()]
