"""Shared login and failed-auth rate limiting (XC, API key)."""

import logging
import math

from django.http import HttpResponse
from rest_framework.throttling import AnonRateThrottle

from dispatcharr.utils import get_client_ip

logger = logging.getLogger(__name__)


class ClientIPRateThrottle(AnonRateThrottle):
    """Per-IP throttle using trusted-proxy-aware ``get_client_ip``.

    DRF's default ``get_ident`` trusts a raw, client-suppliable
    ``X-Forwarded-For`` verbatim (nginx appends rather than replaces it), so
    a caller varying that header on every request would otherwise mint a
    fresh throttle bucket each time and never get rate limited.
    """

    def get_ident(self, request):
        return get_client_ip(request) or super().get_ident(request)

    def _load_history(self, request):
        """Prune and return the cache history, or None when not applicable."""
        if self.rate is None:
            return None
        self.key = self.get_cache_key(request, view=None)
        if self.key is None:
            return None
        self.history = self.cache.get(self.key, [])
        self.now = self.timer()
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
        return self.history

    def is_limited(self, request):
        """Whether *request* is over the rate without consuming a slot."""
        history = self._load_history(request)
        if history is None:
            return False
        return len(history) >= self.num_requests

    def record_failure(self, request):
        """Record one failed attempt. Return True if this call crossed the limit."""
        history = self._load_history(request)
        if history is None:
            return False
        was_limited = len(history) >= self.num_requests
        history.insert(0, self.now)
        self.cache.set(self.key, history, self.duration)
        self.history = history
        return (not was_limited) and len(history) >= self.num_requests


class LoginRateThrottle(ClientIPRateThrottle):
    """Per-IP login throttle (scope ``login``, see REST_FRAMEWORK rates)."""

    scope = "login"


class FailedAuthRateThrottle(ClientIPRateThrottle):
    """Fail-only per-IP throttle; subclasses set ``scope``.

    Only failed credential attempts should call ``record_failure``. Successful
    auth must not consume a slot. Always keys by IP (unlike stock
    ``AnonRateThrottle``, which skips authenticated Django users and reads
    ``request.user``).
    """

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class XcFailedAuthRateThrottle(FailedAuthRateThrottle):
    """Per-IP XC failed-credential throttle (scope ``xc_auth``)."""

    scope = "xc_auth"


class ApiKeyFailedAuthRateThrottle(FailedAuthRateThrottle):
    """Per-IP API-key failed-auth throttle (scope ``api_key_auth``)."""

    scope = "api_key_auth"


def _login_username_from_request(request):
    """Best-effort username from DRF ``request.data`` or Django ``POST``."""
    data = getattr(request, "data", None)
    if data is not None:
        try:
            username = data.get("username")
        except Exception:
            username = None
        if username:
            return username
    post = getattr(request, "POST", None)
    if post is not None:
        return post.get("username") or None
    return None


def _lockout_flag_timeout(wait, duration):
    """Seconds to suppress another lockout event for this IP.

    ``wait`` is the throttle retry delay the caller already computed. Ceil
    keeps the flag up until that delay has fully elapsed.
    """
    seconds = duration if wait is None else wait
    if not seconds:
        seconds = 1
    return max(1, math.ceil(seconds))


def emit_login_rate_limit_lockout(request, username=None, wait=None, throttle=None):
    """Emit one ``login_failed`` event and maybe an inbox notice for this IP.

    Call only after the login throttle has already denied the request.
    ``throttle`` is that instance when the caller has it (admin and proxy),
    so the retry delay comes from history already in memory. JWT passes
    ``wait`` from ``throttled`` instead. This does not read the throttle
    history again.

    ``cache.add`` makes overlapping 429s record a single event. The username
    is read only after that add wins, so a later 429 does not parse the body.
    Any failure is logged and swallowed so the caller can still return 429.
    The inbox notice has its own longer cooldown (see
    ``notify_login_rate_limit_inbox``).
    """
    from django.core.cache import cache

    from core.utils import log_system_event, notify_login_rate_limit_inbox

    try:
        if throttle is None:
            throttle = LoginRateThrottle()
        if wait is None and getattr(throttle, "history", None) is not None:
            wait = throttle.wait()
        timeout = _lockout_flag_timeout(wait, throttle.duration)
        emit_key = f"login_rate_limit_lockout_emitted:{throttle.get_ident(request)}"
        if not cache.add(emit_key, True, timeout=timeout):
            return

        if not username:
            username = _login_username_from_request(request)
        client_ip = get_client_ip(request) or "unknown"
        user_agent = request.META.get("HTTP_USER_AGENT", "unknown")
        log_system_event(
            event_type="login_failed",
            user=username or "unknown",
            client_ip=client_ip,
            user_agent=user_agent,
            reason="Login rate limited",
        )
        logger.info(
            "Login rate limited: user=%s ip=%s",
            username or "unknown",
            client_ip,
        )
        notify_login_rate_limit_inbox()
    except Exception:
        logger.exception("Failed to record login rate limit lockout")


def enforce_login_rate_limit(request, username=None):
    """Return a 429 response when the shared login throttle denies *request*.

    Allowed checks consume a slot in the same ``login`` scope used by
    ``TokenObtainPairView``, so JWT and admin login attempts share one budget.
    Returns ``None`` when the request may proceed.
    """
    throttle = LoginRateThrottle()
    if throttle.allow_request(request, view=None):
        return None

    emit_login_rate_limit_lockout(request, username=username, throttle=throttle)

    wait = throttle.wait()
    response = HttpResponse(
        "Too many login attempts. Try again later.",
        status=429,
        content_type="text/plain; charset=utf-8",
    )
    if wait is not None:
        response["Retry-After"] = str(max(1, int(wait)))
    return response


def xc_failed_auth_limited(request):
    """Return ``(limited, wait_seconds)`` for the XC failed-auth budget."""
    throttle = XcFailedAuthRateThrottle()
    if not throttle.is_limited(request):
        return False, None
    wait = throttle.wait()
    return True, wait


def record_xc_failed_auth(request):
    """Record a failed XC credential attempt.

    Returns True when this failure crossed the rate limit (first trip).
    """
    return XcFailedAuthRateThrottle().record_failure(request)


def api_key_failed_auth_limited(request):
    """Return ``(limited, wait_seconds)`` for the API-key failed-auth budget."""
    throttle = ApiKeyFailedAuthRateThrottle()
    if not throttle.is_limited(request):
        return False, None
    wait = throttle.wait()
    return True, wait


def record_api_key_failed_auth(request):
    """Record a failed API-key attempt.

    Returns True when this failure crossed the rate limit (first trip).
    """
    return ApiKeyFailedAuthRateThrottle().record_failure(request)
