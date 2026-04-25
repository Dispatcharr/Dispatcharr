import hmac
import logging

logger = logging.getLogger(__name__)

# ── Input validation ────────────────────────────────────────────────────────


def _validate_credentials(username, password):
    """Return (clean_username, clean_password) or (None, None) if invalid."""
    if not username or not password:
        return None, None
    if not isinstance(username, str) or not isinstance(password, str):
        return None, None
    username = username.strip()
    if not username:
        return None, None
    # Reject null bytes (injection vector)
    if "\x00" in username or "\x00" in password:
        logger.warning("Auth rejected: null byte in credentials (user=%r)", username[:64])
        return None, None
    return username, password


class PluginAuthBackend:
    """Django authentication backend that delegates to plugin authenticate_ui hooks.

    Plugins can implement an ``authenticate_ui(username, password)`` method
    that returns a ``User`` instance on success or ``None`` to skip.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        from apps.accounts.models import User

        username, password = _validate_credentials(username, password)
        if username is None:
            return None

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
                        logger.info("Plugin '%s' authenticated UI user '%s'", lp.key, username)
                        return result
                except Exception:
                    logger.debug(
                        "Plugin '%s' authenticate_ui failed", lp.key, exc_info=True
                    )

        logger.debug("Plugin UI auth: no plugin authenticated user '%s'", username)
        return None

    def get_user(self, user_id):
        from apps.accounts.models import User

        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


def plugin_authenticate_xc(username, password):
    """Iterate loaded plugins calling authenticate_xc hooks.

    Returns a User on success, or None if no plugin authenticated.
    Mirrors PluginAuthBackend but for XC endpoints.
    """
    from apps.accounts.models import User

    username, password = _validate_credentials(username, password)
    if username is None:
        return None

    try:
        from apps.plugins.loader import PluginManager
        pm = PluginManager.get()
    except Exception:
        return None

    for lp in pm._registry.values():
        if not lp.loaded or not lp.instance:
            continue
        auth_fn = getattr(lp.instance, "authenticate_xc", None)
        if callable(auth_fn):
            try:
                result = auth_fn(username, password)
                if isinstance(result, User):
                    if result.username != username:
                        logger.warning(
                            "Plugin '%s' authenticate_xc returned user '%s' for username '%s' — rejected",
                            lp.key, result.username, username,
                        )
                        continue
                    logger.info("Plugin '%s' authenticated XC user '%s'", lp.key, username)
                    return result
            except Exception:
                logger.debug(
                    "Plugin '%s' authenticate_xc failed", lp.key, exc_info=True
                )

    return None
