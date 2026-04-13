import logging

logger = logging.getLogger(__name__)


class PluginAuthBackend:
    """Django authentication backend that delegates to plugin authenticate_ui hooks.

    Plugins can implement an ``authenticate_ui(username, password)`` method
    that returns a ``User`` instance on success or ``None`` to skip.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        from apps.accounts.models import User

        try:
            from apps.plugins.loader import PluginManager
            pm = PluginManager.get()
        except Exception:
            return None

        for lp in pm._registry.values():
            if not lp.loaded or not lp.instance:
                continue
            auth_fn = getattr(lp.instance, "authenticate_ui", None)
            if callable(auth_fn):
                try:
                    result = auth_fn(username, password)
                    if isinstance(result, User):
                        return result
                except Exception:
                    logger.debug(
                        "Plugin '%s' authenticate_ui failed", lp.key, exc_info=True
                    )
        return None

    def get_user(self, user_id):
        from apps.accounts.models import User

        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


def xc_get_user(request, username=None, password=None):
    """Authenticate an XC API request via xc_password or plugin hooks.

    Returns a User on success, or None if authentication fails.
    A blank xc_password on an existing user means XC is disabled for them.
    """
    from apps.accounts.models import User

    if username is None:
        username = request.GET.get("username")
    if password is None:
        password = request.GET.get("password")

    if not username or not password:
        return None

    # Standard xc_password authentication
    try:
        user = User.objects.get(username=username)
        custom_properties = user.custom_properties or {}
        xc_password = custom_properties.get("xc_password", "")
        # Blank xc_password means XC is disabled for this user
        if not xc_password:
            return None
        if xc_password == password:
            return user
    except User.DoesNotExist:
        user = None

    # Plugin authentication hook fallback
    # Skip if user exists but has blank xc_password (XC disabled)
    if user is not None:
        custom_properties = user.custom_properties or {}
        if not custom_properties.get("xc_password", ""):
            return None

    try:
        from apps.plugins.loader import PluginManager
        pm = PluginManager.get()
        for lp in pm._registry.values():
            if not lp.loaded or not lp.instance:
                continue
            auth_fn = getattr(lp.instance, "authenticate_xc", None)
            if callable(auth_fn):
                result = auth_fn(username, password)
                if isinstance(result, User):
                    return result
    except Exception:
        logger.debug("Plugin XC auth hook unavailable", exc_info=True)

    return None
