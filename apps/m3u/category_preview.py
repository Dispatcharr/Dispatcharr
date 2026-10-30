"""Short-lived XC category payloads shared by previews and normal importers.

No preview writes content or selections. Import reuse always covers every
selected provider category; a partial payload must never replace a full catalog.
"""

import gzip
import json
import zlib

from django.core.cache import cache
from django.utils.crypto import salted_hmac

from core.xtream_codes import Client, normalize_server_url

TTL = 15 * 60
MAX_PREVIEW_ROWS = 50000
MAX_CACHE_BYTES = 8 * 1024 * 1024
MAX_IMPORT_MISSES = 8
METHODS = {
    "live": ("get_live_categories", "get_live_category_streams"),
    "movie": ("get_vod_categories", "get_vod_streams"),
    "series": ("get_series_categories", "get_series"),
}


class CategoryPreviewError(ValueError):
    """A safe, operator-facing error without provider URLs or credentials."""


def known_provider_total(account, scope):
    """A selected-category import cannot replace a previously known full total."""
    properties = account.custom_properties or {}
    if scope == "live":
        counts = properties.get("live_catalog_counts") or {}
    else:
        counts = (properties.get("vod_catalog_counts") or {}).get(
            "movies" if scope == "movie" else "series"
        ) or {}
    return counts.get("provider_total")


def _key(account, scope, suffix):
    if scope not in METHODS:
        raise ValueError("Unknown category preview scope")
    connection = json.dumps(
        [
            account.account_type,
            normalize_server_url(account.server_url),
            account.username,
            account.password,
            account.user_agent_id,
            account.get_user_agent_string(),
        ]
    )
    fingerprint = salted_hmac("m3u.category-preview", connection).hexdigest()
    return f"m3u:category-preview:v1:{account.pk}:{fingerprint}:{scope}:{suffix}"


def remember_categories(account, scope, categories):
    """Remember provider IDs, including distinct provider categories sharing a name."""
    names = {}
    for row in categories:
        if row.get("category_id") is not None:
            names.setdefault(str(row.get("category_name", "Unknown")), []).append(
                str(row["category_id"])
            )
    try:
        cache.set(_key(account, scope, "index"), names, TTL)
    except Exception:
        # Discovery/import must remain usable when the optional cache is down.
        pass
    return names


def _cached_rows(account, scope, provider_id):
    try:
        payload = cache.get(_key(account, scope, f"rows:{provider_id}"))
    except Exception:
        return None
    if payload is None:
        return None
    try:
        rows = json.loads(gzip.decompress(payload))
        _validate_rows(rows, provider_id)
        return rows
    except (OSError, ValueError, TypeError, EOFError, zlib.error):
        try:
            cache.delete(_key(account, scope, f"rows:{provider_id}"))
        except Exception:
            pass
        return None


def _fetch_rows(client, scope, provider_id):
    rows = getattr(client, METHODS[scope][1])(category_id=provider_id)
    _validate_rows(rows, provider_id)
    return rows


def _validate_rows(rows, provider_id):
    if (
        not isinstance(rows, list)
        or len(rows) > MAX_PREVIEW_ROWS
        or any(
            not isinstance(row, dict) or str(row.get("category_id")) != str(provider_id)
            for row in rows
        )
    ):
        raise CategoryPreviewError(
            "The provider did not return a usable single-category response. "
            "Run a regular refresh instead."
        )


def _store_rows(account, scope, provider_id, rows):
    payload = gzip.compress(json.dumps(rows).encode("utf-8"))
    if len(payload) > MAX_CACHE_BYTES:
        raise CategoryPreviewError(
            "This category is too large for a preview. Run a regular refresh."
        )
    cache.set(
        _key(account, scope, f"rows:{provider_id}"),
        payload,
        TTL,
    )


def preview_provider_ids(account, scope, relation, client=None):
    if scope == "live":
        provider_id = (relation.custom_properties or {}).get("xc_id")
        return [str(provider_id)] if provider_id is not None else []
    try:
        names = cache.get(_key(account, scope, "index"))
    except Exception:
        names = None
    if names is None and client is not None:
        names = remember_categories(
            account, scope, getattr(client, METHODS[scope][0])()
        )
    return (names or {}).get(relation.category.name, [])


def cached_preview(account, scope, relation):
    ids = preview_provider_ids(account, scope, relation)
    if not ids:
        return None
    rows = [_cached_rows(account, scope, provider_id) for provider_id in ids]
    if any(items is None for items in rows):
        return None
    return [item for items in rows for item in items]


def can_load_preview(account, scope, relation):
    return bool(
        account.account_type == "XC"
        and account.is_active
        and account.server_url
        and account.username
        and account.password
        and (scope == "live" or (account.custom_properties or {}).get("enable_vod"))
        and (
            (relation.custom_properties or {}).get("xc_id") is not None
            if scope == "live"
            else relation.category.name != "Uncategorized"
        )
    )


def load_preview(account, scope, relation):
    if not can_load_preview(account, scope, relation):
        raise CategoryPreviewError(
            "A targeted preview is unavailable for this category."
        )
    existing = cached_preview(account, scope, relation)
    if existing is not None:
        return existing
    lock = _key(account, scope, f"loading:{relation.pk}")
    try:
        if not cache.add(lock, True, timeout=180):
            raise CategoryPreviewError(
                "This category is already loading. Retry shortly."
            )
    except CategoryPreviewError:
        raise
    except Exception as exc:
        raise CategoryPreviewError(
            "The preview cache is unavailable. Retry shortly."
        ) from exc
    try:
        with Client(
            account.server_url,
            account.username,
            account.password,
            account.get_user_agent_string(),
        ) as client:
            ids = preview_provider_ids(account, scope, relation, client)
            if not ids:
                raise CategoryPreviewError(
                    "This category is no longer listed by the provider. Run a regular refresh."
                )
            result = []
            for provider_id in ids:
                rows = _cached_rows(account, scope, provider_id)
                if rows is None:
                    rows = _fetch_rows(client, scope, provider_id)
                    _store_rows(account, scope, provider_id, rows)
                result.extend(rows)
            return result
    except CategoryPreviewError:
        raise
    except Exception as exc:
        raise CategoryPreviewError(
            "The category could not be loaded from the provider. Check the connection and retry."
        ) from exc
    finally:
        try:
            cache.delete(lock)
        except Exception:
            pass


def import_cached_categories(account, scope, provider_ids, client):
    """Return all selected rows, or None to keep the existing full-fetch path.

    Avoid replacing one efficient catalog request with hundreds of category
    requests. Uncategorized imports require the full catalog as well.
    """
    ids = sorted(set(map(str, provider_ids)))
    if not ids:
        return None
    try:
        cached = {
            provider_id: _cached_rows(account, scope, provider_id)
            for provider_id in ids
        }
        missing = [key for key, rows in cached.items() if rows is None]
        if len(missing) == len(ids) or len(missing) > MAX_IMPORT_MISSES:
            return None
        for provider_id in missing:
            cached[provider_id] = _fetch_rows(client, scope, provider_id)
        result = [item for provider_id in ids for item in cached[provider_id]]
        # Consume only after all selected categories were fetched successfully.
        # The next refresh should see fresh provider data, not replay a preview.
        cache.delete_many(
            [_key(account, scope, f"rows:{provider_id}") for provider_id in ids]
        )
        return result
    except Exception:
        # Cache/provider-category failures must not weaken the existing full
        # import's validation or cause cleanup after an incomplete response.
        return None
