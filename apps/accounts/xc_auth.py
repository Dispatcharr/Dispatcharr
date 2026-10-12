"""Shared Xtream Codes credential checks.

Every XC entry point (API, live, VOD, timeshift) authenticates against the
``xc_password`` custom property via these helpers so comparison stays
constant-time and rules stay in one place.
"""

import hmac
import logging

from django.http import JsonResponse

from apps.accounts.models import User
from apps.accounts.throttling import record_xc_failed_auth, xc_failed_auth_limited
from dispatcharr.utils import get_client_ip, network_access_allowed

logger = logging.getLogger(__name__)

# Failure markers used when building error responses (and in tests).
XC_AUTH_NETWORK = "network"
XC_AUTH_CREDENTIALS = "credentials"
XC_AUTH_RATE_LIMIT = "rate_limit"


def xc_password_matches(user, password):
    """Whether *password* matches *user*'s configured XC password.

    Returns False when the user has no ``xc_password`` set (nothing to
    compare), or when the values differ. Uses ``hmac.compare_digest`` so
    timing does not leak the expected secret. Both sides are compared as
    UTF-8 bytes because ``compare_digest`` raises ``TypeError`` for ``str``
    values containing non-ASCII characters, which a client can send even
    though stored XC passwords are restricted to ASCII-safe characters.
    """
    expected = (user.custom_properties or {}).get("xc_password")
    if not expected:
        return False
    return hmac.compare_digest(str(expected).encode(), str(password).encode())


def get_xc_user(username):
    """Return the User for *username*, or None when the account does not exist."""
    if not username:
        return None
    try:
        return User.objects.get(username=username)
    except User.DoesNotExist:
        return None


def xc_auth_error_response(failure, retry_after=None):
    """HTTP response for an ``authorize_xc_client`` failure reason."""
    if failure == XC_AUTH_NETWORK:
        return JsonResponse({"error": "Forbidden"}, status=403)
    if failure == XC_AUTH_RATE_LIMIT:
        response = JsonResponse({"error": "Too many attempts"}, status=429)
        if retry_after is not None:
            response["Retry-After"] = str(max(1, int(retry_after)))
        return response
    return JsonResponse({"error": "Unauthorized"}, status=401)


def _xc_credential_failure(request, username):
    """Record a failed credential attempt and return the 401 response.

    When this failure crosses the per-IP rate limit, emit one ``login_failed``
    system event and (subject to cooldown) an admin inbox notice.
    """
    if record_xc_failed_auth(request):
        _emit_xc_auth_lockout(request, username)
    return None, xc_auth_error_response(XC_AUTH_CREDENTIALS)


def _emit_xc_auth_lockout(request, username):
    """Log the lockout trip and maybe refresh the cooldown inbox notice."""
    from core.utils import log_system_event, notify_xc_auth_lockout_inbox

    client_ip = get_client_ip(request) or "unknown"
    user_agent = request.META.get("HTTP_USER_AGENT", "unknown")
    log_system_event(
        event_type="login_failed",
        user=username or "unknown",
        client_ip=client_ip,
        user_agent=user_agent,
        reason="XC auth rate limited",
    )
    logger.info(
        "XC auth rate limited: user=%s ip=%s",
        username or "unknown",
        client_ip,
    )
    try:
        notify_xc_auth_lockout_inbox()
    except Exception:
        logger.exception("Failed to create XC auth lockout inbox notice")


def authorize_xc_client(request, username, password, network_key):
    """Return ``(user, None)`` on success, or ``(None, error_response)``.

    Runs two ``network_access_allowed`` calls (system, then user). The client
    must pass both.
    - System: CoreSettings CIDR allowlist for *network_key*. Checked first
      with no user so a blocked client never hits the database.
    - User: after the user row is loaded and before the password, so a
      denied client is not told whether the password was right. When the user
      has no ``allowed_networks`` for *network_key*, this follows the system
      allowlist; a non-empty list can only tighten access.

    Failed credential attempts are rate-limited per client IP (shared Redis
    cache, scope ``xc_auth``). Successful auth and network denials do not
    consume that budget.
    """
    # System-wide allowlist (CoreSettings), no user row involved.
    system_network_ok = network_access_allowed(request, network_key, user=None)
    if not system_network_ok:
        return None, xc_auth_error_response(XC_AUTH_NETWORK)

    limited, wait = xc_failed_auth_limited(request)
    if limited:
        return None, xc_auth_error_response(XC_AUTH_RATE_LIMIT, retry_after=wait)

    if not username or not password:
        return _xc_credential_failure(request, username)

    user = get_xc_user(username)
    if user is None:
        return _xc_credential_failure(request, username)

    # Per-user allowed_networks (and system list again inside the helper).
    user_network_ok = network_access_allowed(request, network_key, user=user)
    if not user_network_ok:
        return None, xc_auth_error_response(XC_AUTH_NETWORK)

    if not xc_password_matches(user, password):
        return _xc_credential_failure(request, username)

    return user, None
