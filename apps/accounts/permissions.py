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
