"""Shared login and XC failed-auth rate limiting."""

from django.http import HttpResponse
from rest_framework.throttling import AnonRateThrottle

from dispatcharr.utils import get_client_ip


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


class XcFailedAuthRateThrottle(ClientIPRateThrottle):
    """Per-IP XC failed-credential throttle (scope ``xc_auth``).

    Only failed credential attempts should call ``record_failure``. Successful
    XC auth must not consume a slot. Always keys by IP (unlike stock
    ``AnonRateThrottle``, which skips authenticated Django users and reads
    ``request.user``).
    """

    scope = "xc_auth"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


def enforce_login_rate_limit(request):
    """Return a 429 response when the shared login throttle denies *request*.

    Allowed checks consume a slot in the same ``login`` scope used by
    ``TokenObtainPairView``, so JWT and admin login attempts share one budget.
    Returns ``None`` when the request may proceed.
    """
    throttle = LoginRateThrottle()
    if throttle.allow_request(request, view=None):
        return None

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
