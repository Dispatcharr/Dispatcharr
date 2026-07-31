"""Parent-scoped VOD image proxy helpers.

Fetches image URLs already stored on Movie / Series / Episode records
(custom_properties), without accepting arbitrary client-supplied URLs.
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


def resolve_vod_image_url(obj, kind: str, index: int = 0) -> str | None:
    """Resolve a stored image URL from obj.custom_properties for an allowlisted kind."""
    if kind not in VOD_IMAGE_KINDS:
        return None

    props = obj.custom_properties or {}

    if kind == "backdrop":
        paths = props.get("backdrop_path") or []
        if isinstance(paths, str):
            paths = [paths]
        if not isinstance(paths, (list, tuple)):
            return None
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
) -> str:
    """Assemble a proxy URL from precomputed prefix/suffix (no reverse)."""
    # Keep query building allocation-light for XC list hot paths.
    parts = [f"{prefix}{pk}{suffix}?kind={kind}"]
    if kind == "backdrop":
        parts.append(f"&index={index}")
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
                format_vod_image_url(prefix, suffix, pk, "backdrop", index=i, source_url=url)
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
) -> str:
    """Rewrite a single absolute image URL to its parent-scoped proxy URL."""
    if not is_proxyable_image_url(url):
        return url or ""
    if url_parts is None:
        url_parts = vod_image_url_parts(request, resource)
    prefix, suffix = url_parts
    return format_vod_image_url(prefix, suffix, pk, kind, source_url=url)


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

    if kind not in VOD_IMAGE_KINDS:
        raise Http404("Image not found")

    url = resolve_vod_image_url(obj, kind, index)
    if not url:
        raise Http404("Image not found")

    return serve_vod_image(url)
