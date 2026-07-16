"""OpenAPI schema views that are safe under gevent concurrency.

DRF's AutoSchema descriptor keeps mutable per-class state (``self.view``).
When uWSGI serves requests with gevent, concurrent ``/api/schema/`` builds
interleave on that state and raise:

    AssertionError: Schema generation REQUIRES a view instance

Only one schema build runs at a time per process (single-flight). The
finished schema is stored in Django's cache (Redis) so all workers share it.
Waiters block on an Event instead of holding a lock across DB I/O, which
avoids gevent deadlocks with the connection pool.
"""

from __future__ import annotations

import copy
import logging
import threading
from typing import Dict, Optional

from django.conf import settings
from django.core.cache import cache
from rest_framework.response import Response

from drf_spectacular.views import SpectacularAPIView

logger = logging.getLogger(__name__)

# Greenlet-safe after gevent monkey-patching.
_guard = threading.Lock()
_in_progress: Dict[str, threading.Event] = {}
# Same-process handoff when cache.set fails so waiters are not left empty-handed.
_flight_results: Dict[str, dict] = {}

_SCHEMA_CACHE_PREFIX = "openapi:schema:"
_SCHEMA_CACHE_VER_KEY = f"{_SCHEMA_CACHE_PREFIX}cache_ver"


def _cache_supports_delete_pattern() -> bool:
    return callable(getattr(cache, "delete_pattern", None))


def clear_schema_cache() -> None:
    """Invalidate cached schemas (tests / forced refresh after deploy)."""
    with _guard:
        _flight_results.clear()
    try:
        if _cache_supports_delete_pattern():
            cache.delete_pattern(f"{_SCHEMA_CACHE_PREFIX}*")
            return
        ver = cache.get(_SCHEMA_CACHE_VER_KEY) or 0
        cache.set(_SCHEMA_CACHE_VER_KEY, int(ver) + 1, timeout=None)
    except Exception:
        logger.warning("Failed to clear OpenAPI schema cache", exc_info=True)


def _key_namespace() -> str:
    """Stable on Redis (pattern delete); versioned on LocMem for test clears."""
    if _cache_supports_delete_pattern():
        return "shared"
    try:
        ver = cache.get(_SCHEMA_CACHE_VER_KEY)
        if ver is None:
            cache.add(_SCHEMA_CACHE_VER_KEY, 1, timeout=None)
            ver = cache.get(_SCHEMA_CACHE_VER_KEY) or 1
        return f"v{int(ver)}"
    except Exception:
        return "v1"


class LockedSpectacularAPIView(SpectacularAPIView):
    """SpectacularAPIView with single-flight generation and Django cache."""

    def _resolve_version(self, request):
        return self.api_version or request.version or self._get_version_parameter(
            request
        )

    def _cache_key(self, request) -> str:
        version = self._resolve_version(request)
        lang = request.GET.get("lang") if settings.USE_I18N else None
        urlconf = self.urlconf
        if urlconf is None:
            urlconf_part = "default"
        else:
            urlconf_part = getattr(urlconf, "__name__", None) or type(urlconf).__name__
        patterns_part = "custom" if self.patterns is not None else "default"
        return (
            f"{_SCHEMA_CACHE_PREFIX}{_key_namespace()}:"
            f"{version}:{lang}:{self.serve_public}:{urlconf_part}:{patterns_part}"
        )

    def _cache_get(self, key: str) -> Optional[dict]:
        try:
            return cache.get(key)
        except Exception:
            logger.warning("OpenAPI schema cache get failed", exc_info=True)
            return None

    def _cache_set(self, key: str, schema: dict) -> None:
        try:
            # Use CACHES['default'] TIMEOUT (3600s in settings).
            cache.set(key, schema)
        except Exception:
            logger.warning("OpenAPI schema cache set failed", exc_info=True)

    def _get_schema_response(self, request):
        version = self._resolve_version(request)
        cache_key = self._cache_key(request)

        cached = self._cache_get(cache_key)
        if cached is not None:
            return self._schema_response(request, version, cached)

        with _guard:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return self._schema_response(request, version, cached)

            event = _in_progress.get(cache_key)
            if event is None:
                event = threading.Event()
                _in_progress[cache_key] = event
                is_builder = True
            else:
                is_builder = False

        if not is_builder:
            if not event.wait(timeout=120):
                return Response(
                    {"detail": "Timed out waiting for OpenAPI schema generation."},
                    status=503,
                )
            cached = self._cache_get(cache_key)
            if cached is None:
                with _guard:
                    cached = _flight_results.get(cache_key)
            if cached is None:
                return Response(
                    {"detail": "OpenAPI schema generation failed."},
                    status=500,
                )
            return self._schema_response(request, version, cached)

        try:
            generator = self.generator_class(
                urlconf=self.urlconf,
                api_version=version,
                patterns=self.patterns,
            )
            schema = generator.get_schema(
                request=request, public=self.serve_public
            )
            with _guard:
                _flight_results[cache_key] = schema
            self._cache_set(cache_key, schema)
            return self._schema_response(request, version, schema)
        finally:
            with _guard:
                _in_progress.pop(cache_key, None)
            event.set()

    def _schema_response(self, request, version, schema: dict) -> Response:
        # LocMem returns the same object; deepcopy keeps responses isolated.
        return Response(
            data=copy.deepcopy(schema),
            headers={
                "Content-Disposition": (
                    f'inline; filename="{self._get_filename(request, version)}"'
                )
            },
        )
