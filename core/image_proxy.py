"""Shared local/remote image proxy helpers for channel logos and VOD art."""

from __future__ import annotations

import logging
import mimetypes
import os
import time
from urllib.parse import urljoin

import requests
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.utils.http import http_date

from core.http_security import validate_outbound_http_url
from core.models import CoreSettings
from core.utils import resolve_safe_local_data_path

logger = logging.getLogger(__name__)

# Negative cache for remote image URLs that failed to fetch.
# Shared across channel logos and VOD image/logo proxies.
image_fetch_failures = {}
IMAGE_FETCH_FAIL_TTL = 300  # seconds
IMAGE_FETCH_TOTAL_TIMEOUT = 10  # seconds
IMAGE_FETCH_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
IMAGE_FETCH_MAX_REDIRECTS = 5

# Active SVG opened as a document must not run script on this origin.
_IMAGE_RESPONSE_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


def _remember_fetch_failure(url: str, failure_cache: dict, fail_ttl: int) -> None:
    now = time.monotonic()
    failure_cache[url] = now + fail_ttl
    if len(failure_cache) > 256:
        for key in [k for k, expiry in failure_cache.items() if expiry <= now]:
            failure_cache.pop(key, None)


def sniff_image_content_type(body: bytes) -> str | None:
    """Return a safe image Content-Type from magic bytes, or None if unsupported."""
    if not body:
        return None

    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    if body.startswith((b"\x00\x00\x01\x00", b"\x00\x00\x02\x00")):
        return "image/x-icon"
    if body.startswith(b"BM") and len(body) >= 6:
        return "image/bmp"

    # SVG: allow BOM/whitespace, XML decl, DOCTYPE svg, comments, then <svg>.
    # Reject HTML documents even if they embed an <svg> tag.
    sample = body[:8192].lstrip()
    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:].lstrip()
    lower = sample.lower()
    head = lower[:64]
    if (
        head.startswith(b"<!doctype html")
        or head.startswith(b"<html")
        or head.startswith(b"<head")
        or head.startswith(b"<body")
        or head.startswith(b"<script")
        or b"<html" in lower
    ):
        return None
    if b"<svg" in lower:
        return "image/svg+xml"
    return None


def _apply_image_security_headers(response: HttpResponse, content_type: str) -> None:
    response["X-Content-Type-Options"] = "nosniff"
    if content_type.startswith("image/svg"):
        response["Content-Security-Policy"] = _IMAGE_RESPONSE_CSP


def _read_limited_body(remote_response, *, url: str, failure_cache: dict, fail_ttl: int) -> bytes:
    chunks = []
    total = 0
    deadline = time.monotonic() + IMAGE_FETCH_TOTAL_TIMEOUT
    for chunk in remote_response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        total += len(chunk)
        if total > IMAGE_FETCH_MAX_BYTES:
            raise Http404("Remote image too large")
        if time.monotonic() > deadline:
            _remember_fetch_failure(url, failure_cache, fail_ttl)
            raise Http404("Remote image fetch timed out")
        chunks.append(chunk)
    return b"".join(chunks)


def _fetch_remote_image(
    url: str,
    *,
    failure_cache: dict,
    fail_ttl: int,
    user_agent: str,
) -> tuple[bytes, str, dict]:
    """Fetch *url* with SSRF checks on every hop. Returns body, type, upstream headers."""
    current_url = url
    headers = {"User-Agent": user_agent}

    for _ in range(IMAGE_FETCH_MAX_REDIRECTS + 1):
        try:
            validate_outbound_http_url(current_url, allow_private=True, allow_loopback=False)
        except ValueError as exc:
            _remember_fetch_failure(url, failure_cache, fail_ttl)
            logger.warning("Blocked unsafe remote image URL %s: %s", current_url, exc)
            raise Http404("Remote image not allowed") from exc

        remote_response = requests.get(
            current_url,
            stream=True,
            timeout=(3, 5),
            allow_redirects=False,
            headers=headers,
        )
        try:
            status = remote_response.status_code
            if status in (301, 302, 303, 307, 308):
                location = remote_response.headers.get("Location")
                if not location:
                    _remember_fetch_failure(url, failure_cache, fail_ttl)
                    raise Http404("Remote image not found")
                current_url = urljoin(current_url, location)
                continue

            if status != 200:
                _remember_fetch_failure(url, failure_cache, fail_ttl)
                raise Http404("Remote image not found")

            body = _read_limited_body(
                remote_response,
                url=url,
                failure_cache=failure_cache,
                fail_ttl=fail_ttl,
            )
            upstream_headers = {
                "Cache-Control": remote_response.headers.get("Cache-Control"),
                "Last-Modified": remote_response.headers.get("Last-Modified"),
            }
        finally:
            remote_response.close()

        content_type = sniff_image_content_type(body)
        if not content_type:
            _remember_fetch_failure(url, failure_cache, fail_ttl)
            raise Http404("Remote image type not allowed")

        return body, content_type, upstream_headers

    _remember_fetch_failure(url, failure_cache, fail_ttl)
    raise Http404("Remote image redirect limit exceeded")


def serve_local_or_remote_image(
    url: str | None,
    *,
    failure_cache: dict | None = None,
    fail_ttl: int = IMAGE_FETCH_FAIL_TTL,
    log_label: str = "image",
):
    """Stream a local ``/data/...`` file or proxy a remote http(s) image.

    Applies connect/read timeouts, a total download deadline, and a max body
    size so slow or huge upstreams cannot pin workers. Failed remote URLs are
    negative-cached in ``failure_cache`` (defaults to the process-wide map).

    Remote fetches re-validate the target after DNS on every redirect hop,
    allow private LAN addresses (for locally hosted artwork), and reject
    loopback/link-local/metadata targets. Response types are taken from
    magic bytes (JPEG/PNG/GIF/WebP/ICO/BMP/SVG), not upstream Content-Type.

    Missing or unreachable images raise ``Http404``
    """
    if failure_cache is None:
        failure_cache = image_fetch_failures

    if not url:
        raise Http404("Image not found")

    if url.startswith("/data"):
        safe_path = resolve_safe_local_data_path(url)
        if safe_path is None or not os.path.exists(safe_path):
            logger.error("%s file not found or unsafe path: %s", log_label, url)
            raise Http404("Image not found")

        try:
            stat = os.stat(safe_path)
            content_type, _ = mimetypes.guess_type(safe_path)
            if not content_type:
                content_type = "image/jpeg"

            # StreamingHttpResponse closes the file when the response finishes.
            response = StreamingHttpResponse(
                open(safe_path, "rb"),
                content_type=content_type,
            )
            response["Cache-Control"] = "public, max-age=14400"
            response["Last-Modified"] = http_date(stat.st_mtime)
            response["Content-Disposition"] = 'inline; filename="{}"'.format(
                os.path.basename(safe_path)
            )
            _apply_image_security_headers(response, content_type)
            return response
        except Exception as e:
            logger.error("Error serving %s file %s: %s", log_label, safe_path, e)
            return HttpResponse(status=500)

    if not url.startswith(("http://", "https://")):
        raise Http404("Image not found")

    fail_expiry = failure_cache.get(url)
    if fail_expiry and time.monotonic() < fail_expiry:
        raise Http404("Remote image temporarily unavailable")

    try:
        body, content_type, upstream_headers = _fetch_remote_image(
            url,
            failure_cache=failure_cache,
            fail_ttl=fail_ttl,
            user_agent=CoreSettings.get_default_user_agent(),
        )
        failure_cache.pop(url, None)

        response = HttpResponse(body, content_type=content_type)
        response["Content-Length"] = str(len(body))
        if upstream_headers.get("Cache-Control"):
            response["Cache-Control"] = upstream_headers["Cache-Control"]
        if upstream_headers.get("Last-Modified"):
            response["Last-Modified"] = upstream_headers["Last-Modified"]
        response["Content-Disposition"] = 'inline; filename="{}"'.format(
            os.path.basename(url.split("?", 1)[0]) or "image"
        )
        _apply_image_security_headers(response, content_type)
        return response
    except Http404:
        raise
    except requests.exceptions.RequestException as e:
        _remember_fetch_failure(url, failure_cache, fail_ttl)
        logger.warning("Error fetching remote %s %s: %s", log_label, url, e)
        raise Http404("Error fetching remote image") from e
