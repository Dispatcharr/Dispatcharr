"""Parent-scoped VOD image proxy helpers.

Fetches image URLs already stored on Movie / Series / Episode records
(and prefers per-provider relation artwork when available), without accepting
arbitrary client-supplied URLs.
"""

from __future__ import annotations

import hashlib

from django.http import Http404
from django.urls import reverse

from core.image_proxy import serve_local_or_remote_image
from core.utils import build_absolute_uri_with_port

# Allowlisted kinds resolved from custom_properties on the parent object.
VOD_IMAGE_KINDS = frozenset({"backdrop", "movie_image", "poster_path"})


def is_proxyable_image_url(url: str | None) -> bool:
    """Return True when url is something our proxy can fetch."""
    if not url or not isinstance(url, str):
        return False
    return url.startswith(("http://", "https://", "/data"))


def _as_backdrop_list(value) -> list:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def get_relation_artwork(custom_properties) -> dict:
    """Extract movie_image / backdrop_path from movie, series, or episode relation shapes.

    Checked in order of how authoritative the data is:
    - Episode relations store the XC episode payload under ``info`` (with nested
      ``info.info``).
    - Movie/series advanced refresh stores ``detailed_info``.
    - Every movie/series relation stores the raw provider list entry under
      ``basic_data`` (e.g. XC's ``stream_icon`` / ``cover`` / ``backdrop_path``),
      refreshed on every list sync even when advanced detail was never fetched.
    """
    empty = {"movie_image": "", "backdrop_path": []}
    if not custom_properties or not isinstance(custom_properties, dict):
        return empty

    candidates = []
    info = custom_properties.get("info")
    if isinstance(info, dict):
        candidates.append(info)
        nested = info.get("info")
        if isinstance(nested, dict):
            candidates.append(nested)
    detailed = custom_properties.get("detailed_info")
    if isinstance(detailed, dict):
        candidates.append(detailed)
    basic = custom_properties.get("basic_data")
    if isinstance(basic, dict):
        candidates.append(basic)
    candidates.append(custom_properties)

    movie_image = ""
    backdrop_path = []
    for candidate in candidates:
        if not movie_image:
            raw = (
                candidate.get("movie_image")
                or candidate.get("cover_big")
                or candidate.get("stream_icon")
                or candidate.get("cover")
                or ""
            )
            if isinstance(raw, str) and raw.strip():
                movie_image = raw.strip()
        if not backdrop_path:
            backdrop_path = _as_backdrop_list(candidate.get("backdrop_path"))

    return {"movie_image": movie_image, "backdrop_path": backdrop_path}


def prefer_relation_artwork(relation_custom_properties, object_custom_properties) -> dict:
    """Prefer relation artwork, falling back to shared object custom_properties."""
    from_rel = get_relation_artwork(relation_custom_properties)
    obj_props = object_custom_properties if isinstance(object_custom_properties, dict) else {}
    movie_image = from_rel["movie_image"] or (obj_props.get("movie_image") or "")
    if isinstance(movie_image, str):
        movie_image = movie_image.strip()
    else:
        movie_image = ""
    backdrop_path = from_rel["backdrop_path"] or _as_backdrop_list(obj_props.get("backdrop_path"))
    return {"movie_image": movie_image, "backdrop_path": backdrop_path}


def _best_image_relation(obj, m3u_account_id=None):
    """Highest-priority active relation for obj, or a specific account when given."""
    from apps.vod.models import (
        Episode,
        Movie,
        M3UEpisodeRelation,
        M3UMovieRelation,
        M3USeriesRelation,
        Series,
    )

    if isinstance(obj, Episode):
        qs = M3UEpisodeRelation.objects.filter(
            episode_id=obj.pk,
            m3u_account__is_active=True,
        )
    elif isinstance(obj, Movie):
        qs = M3UMovieRelation.objects.filter(
            movie_id=obj.pk,
            m3u_account__is_active=True,
        )
    elif isinstance(obj, Series):
        qs = M3USeriesRelation.objects.filter(
            series_id=obj.pk,
            m3u_account__is_active=True,
        )
    else:
        return None

    if m3u_account_id is not None:
        qs = qs.filter(m3u_account_id=m3u_account_id)

    return qs.order_by("-m3u_account__priority", "id").only("custom_properties").first()


def _url_from_props(props: dict, kind: str, index: int = 0) -> str | None:
    if kind == "backdrop":
        paths = _as_backdrop_list(props.get("backdrop_path"))
        try:
            index = int(index)
        except (TypeError, ValueError):
            return None
        if index < 0 or index >= len(paths):
            return None
        url = paths[index]
    elif kind == "movie_image":
        url = props.get("movie_image") or ""
    else:  # poster_path
        url = props.get("poster_path") or ""

    if not is_proxyable_image_url(url):
        return None
    return url


def resolve_vod_image_url(obj, kind: str, index: int = 0, m3u_account_id=None) -> str | None:
    """Resolve a stored image URL for an allowlisted kind.

    Prefers artwork from the highest-priority active provider relation (or a
    specific account when ``m3u_account_id`` is set), then falls back to the
    shared object's custom_properties.
    """
    if kind not in VOD_IMAGE_KINDS:
        return None

    if getattr(obj, "pk", None):
        relation = _best_image_relation(obj, m3u_account_id=m3u_account_id)
        if relation is not None:
            art = prefer_relation_artwork(relation.custom_properties, obj.custom_properties)
            # poster_path is only on shared object props today.
            props = {
                "movie_image": art["movie_image"],
                "backdrop_path": art["backdrop_path"],
                "poster_path": (obj.custom_properties or {}).get("poster_path"),
            }
            url = _url_from_props(props, kind, index)
            if url:
                return url

    return _url_from_props(obj.custom_properties or {}, kind, index)


def vod_image_url_parts(request, resource: str) -> tuple[str, str]:
    """Build prefix/suffix for parent-scoped image URLs with a single reverse().

    Mirrors the XC logo URL pattern: reverse once with pk=0, then string-concat
    the real pk per row. resource is the DRF basename: movie, series, or episode.

    Returns (prefix, suffix) such that f"{prefix}{pk}{suffix}?kind=..." is valid.
    """
    sample = reverse(f"api:vod:{resource}-image", args=[0])
    prefix_raw, _, suffix_raw = sample.partition("/0/")
    if request is not None:
        base = build_absolute_uri_with_port(request, "")
        return base + prefix_raw + "/", "/" + suffix_raw
    return prefix_raw + "/", "/" + suffix_raw


def format_vod_image_url(
    prefix: str,
    suffix: str,
    pk,
    kind: str,
    index: int = 0,
    source_url: str | None = None,
    m3u_account_id=None,
) -> str:
    """Assemble a proxy URL from precomputed prefix/suffix (no reverse)."""
    # Keep query building allocation-light for XC list hot paths.
    parts = [f"{prefix}{pk}{suffix}?kind={kind}"]
    if kind == "backdrop":
        parts.append(f"&index={index}")
    if m3u_account_id is not None:
        parts.append(f"&m3u_account_id={m3u_account_id}")
    if source_url:
        parts.append(f"&v={hashlib.md5(source_url.encode()).hexdigest()[:8]}")
    return "".join(parts)


def rewrite_backdrop_paths(
    request,
    resource: str,
    pk,
    backdrop_path,
    *,
    url_parts: tuple[str, str] | None = None,
    m3u_account_id=None,
) -> list:
    """Rewrite absolute backdrop URLs to parent-scoped proxy URLs.

    Relative or empty entries are left unchanged so XC clients keep existing behavior.
    Pass url_parts=(prefix, suffix) from vod_image_url_parts() when rewriting many rows
    so reverse() runs once outside the loop.
    """
    if not backdrop_path:
        return []
    if isinstance(backdrop_path, str):
        backdrop_path = [backdrop_path]
    if not isinstance(backdrop_path, (list, tuple)):
        return []

    if url_parts is None:
        url_parts = vod_image_url_parts(request, resource)
    prefix, suffix = url_parts

    rewritten = []
    for i, url in enumerate(backdrop_path):
        if is_proxyable_image_url(url):
            rewritten.append(
                format_vod_image_url(
                    prefix,
                    suffix,
                    pk,
                    "backdrop",
                    index=i,
                    source_url=url,
                    m3u_account_id=m3u_account_id,
                )
            )
        else:
            rewritten.append(url)
    return rewritten


def rewrite_single_image_url(
    request,
    resource: str,
    pk,
    kind: str,
    url: str | None,
    *,
    url_parts: tuple[str, str] | None = None,
    m3u_account_id=None,
) -> str:
    """Rewrite a single absolute image URL to its parent-scoped proxy URL."""
    if not is_proxyable_image_url(url):
        return url or ""
    if url_parts is None:
        url_parts = vod_image_url_parts(request, resource)
    prefix, suffix = url_parts
    return format_vod_image_url(
        prefix,
        suffix,
        pk,
        kind,
        source_url=url,
        m3u_account_id=m3u_account_id,
    )


def vodlogo_cache_url(request, logo) -> str:
    """Absolute VOD logo cache URL with a short source-URL hash for cache busting.

    Shared by VODLogoSerializer and the movie/series provider-info endpoints so
    the URL format (and cache-busting behavior) stays in one place.
    """
    if not logo:
        return ""
    url_hash = hashlib.md5((logo.url or "").encode()).hexdigest()[:8]
    path = f"{reverse('api:vod:vodlogo-cache', args=[logo.id])}?v={url_hash}"
    if request is not None:
        return build_absolute_uri_with_port(request, path)
    return path


def serve_vod_image(url: str):
    """Stream a local or remote VOD image via the shared core image proxy."""
    return serve_local_or_remote_image(url, log_label="VOD image")


def vod_image_action(view, request, resource: str = ""):
    """Shared detail action handler for Movie / Series / Episode image endpoints.

    ``resource`` is accepted for call-site clarity (movie/series/episode) but is
    not needed at serve time: the view's queryset already scopes the object.
    """
    obj = view.get_object()
    kind = request.query_params.get("kind", "backdrop")
    index = request.query_params.get("index", "0")
    account_id = request.query_params.get("m3u_account_id")
    if account_id is not None:
        try:
            account_id = int(account_id)
        except (TypeError, ValueError):
            account_id = None

    if kind not in VOD_IMAGE_KINDS:
        raise Http404("Image not found")

    url = resolve_vod_image_url(obj, kind, index, m3u_account_id=account_id)
    if not url:
        raise Http404("Image not found")

    return serve_vod_image(url)
