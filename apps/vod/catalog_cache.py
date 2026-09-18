"""Versioned XC VOD catalog cache helpers."""

import hashlib
import logging
import time

from django.core.cache import cache

GENERATION_KEY = "xc_vod_catalog:generation"
SELECTION_GENERATION_KEY = "xc_vod_selection:generation"
logger = logging.getLogger(__name__)
_fallback_generation = str(time.time_ns())
_fallback_selection_generation = _fallback_generation


def safe_cache_get(key, default=None):
    try:
        return cache.get(key, default)
    except Exception as exc:
        logger.warning("VOD cache read failed for %s: %s", key, exc)
        return default


def safe_cache_set(key, value, timeout=None):
    try:
        cache.set(key, value, timeout=timeout)
        return True
    except Exception as exc:
        logger.warning("VOD cache write failed for %s: %s", key, exc)
        return False


def catalog_generation():
    generation = safe_cache_get(GENERATION_KEY)
    if generation is None:
        generation = str(time.time_ns())
        try:
            cache.add(GENERATION_KEY, generation, timeout=None)
        except Exception:
            return _fallback_generation
        generation = safe_cache_get(GENERATION_KEY, generation)
    return generation


def selection_catalog_generation():
    """Version only source/metadata changes that affect prepared profiles."""
    generation = safe_cache_get(SELECTION_GENERATION_KEY)
    if generation is None:
        # Redis is recreated when the all-in-one container starts. PostgreSQL
        # is therefore the authority for whether prepared catalogs are still
        # current; Redis only caches that durable value at runtime.
        generation = None
        try:
            from .models import VODCatalogState

            generation = VODCatalogState.objects.filter(pk=1).values_list(
                "selection_generation", flat=True
            ).first()
            if not generation:
                generation = str(time.time_ns())
                state, _ = VODCatalogState.objects.get_or_create(
                    pk=1,
                    defaults={"selection_generation": generation},
                )
                generation = state.selection_generation
        except Exception:
            # App startup and migrations can call this before the table exists.
            # Recovering from a prepared policy keeps upgrades from needlessly
            # invalidating an existing catalog until the state row is created.
            try:
                from .models import VODAccessPolicy

                generation = (
                    VODAccessPolicy.objects.exclude(
                        selection_catalog_generation=""
                    )
                    .order_by("-selection_completed_at")
                    .values_list("selection_catalog_generation", flat=True)
                    .first()
                )
            except Exception:
                generation = None
        generation = str(generation or time.time_ns())
        try:
            from .models import VODCatalogState

            VODCatalogState.objects.update_or_create(
                pk=1,
                defaults={"selection_generation": generation},
            )
        except Exception:
            pass
        try:
            cache.add(SELECTION_GENERATION_KEY, generation, timeout=None)
        except Exception:
            return _fallback_selection_generation
        generation = safe_cache_get(SELECTION_GENERATION_KEY, generation)
    return generation


def bump_selection_catalog_generation():
    global _fallback_selection_generation
    generation = str(time.time_ns())
    _fallback_selection_generation = generation
    try:
        from .models import VODCatalogState

        VODCatalogState.objects.update_or_create(
            pk=1,
            defaults={"selection_generation": generation},
        )
    except Exception as exc:
        # Migrations and first-time setup may call this before the table exists.
        logger.warning("Could not persist VOD selection generation: %s", exc)
    safe_cache_set(SELECTION_GENERATION_KEY, generation, timeout=None)
    return generation


def bump_catalog_generation(*, invalidate_selections=True):
    global _fallback_generation
    generation = str(time.time_ns())
    _fallback_generation = generation
    safe_cache_set(GENERATION_KEY, generation, timeout=None)
    if invalidate_selections:
        bump_selection_catalog_generation()
    return generation


def catalog_cache_key(request, user, action, category_id=None):
    policy = getattr(user, "_vod_access_policy", None)
    policy_marker = (
        f"{policy.id}:{policy.updated_at.timestamp()}" if policy else "legacy"
    )
    visibility = "adult-hidden" if (
        getattr(user, "user_level", 0) < 10
        and (getattr(user, "custom_properties", None) or {}).get(
            "hide_adult_content", False
        )
    ) else "all"
    host = request.get_host() if request else ""
    digest = hashlib.sha256(
        f"{host}|{user.id}|{policy_marker}|{visibility}|{category_id or ''}".encode()
    ).hexdigest()[:24]
    return f"xc_vod_catalog:{catalog_generation()}:{action}:{digest}"
