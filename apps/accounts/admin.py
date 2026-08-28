from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.models import Group
from django.views.decorators.cache import never_cache

from .models import User
from .throttling import enforce_login_rate_limit


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = (
        (None, {'fields': ('username', 'password', 'avatar_config', 'groups')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

# Unregister default Group admin and re-register it.
admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)

# Defense in depth: if /admin/login/ is reachable (e.g. nginx rule missed),
# share the same per-IP "login" throttle budget as JWT token obtain.
if not getattr(admin.site, "_dispatcharr_login_rate_limited", False):
    _original_admin_login = admin.site.login

    @never_cache
    @login_not_required
    def _rate_limited_admin_login(request, extra_context=None):
        if request.method == "POST":
            throttled = enforce_login_rate_limit(request)
            if throttled is not None:
                return throttled
        return _original_admin_login(request, extra_context=extra_context)

    admin.site.login = _rate_limited_admin_login
    admin.site._dispatcharr_login_rate_limited = True

