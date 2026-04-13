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
