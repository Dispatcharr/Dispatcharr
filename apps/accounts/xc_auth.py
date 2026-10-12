"""Shared Xtream Codes credential checks.

Every XC entry point (API, live, VOD, timeshift) authenticates against the
``xc_password`` custom property via these helpers so comparison stays
constant-time and rules stay in one place.
"""

import hmac

from django.http import JsonResponse

from apps.accounts.models import User
from dispatcharr.utils import network_access_allowed

# Failure markers used when building error responses (and in tests).
XC_AUTH_NETWORK = "network"
XC_AUTH_CREDENTIALS = "credentials"


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


def xc_auth_error_response(failure):
    """HTTP response for an ``authorize_xc_client`` failure reason."""
    if failure == XC_AUTH_NETWORK:
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse({"error": "Unauthorized"}, status=401)


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
    """
    # System-wide allowlist (CoreSettings), no user row involved.
    system_network_ok = network_access_allowed(request, network_key, user=None)
    if not system_network_ok:
        return None, xc_auth_error_response(XC_AUTH_NETWORK)

    if not username or not password:
        return None, xc_auth_error_response(XC_AUTH_CREDENTIALS)

    user = get_xc_user(username)
    if user is None:
        return None, xc_auth_error_response(XC_AUTH_CREDENTIALS)

    # Per-user allowed_networks (and system list again inside the helper).
    user_network_ok = network_access_allowed(request, network_key, user=user)
    if not user_network_ok:
        return None, xc_auth_error_response(XC_AUTH_NETWORK)

    if not xc_password_matches(user, password):
        return None, xc_auth_error_response(XC_AUTH_CREDENTIALS)

    return user, None
