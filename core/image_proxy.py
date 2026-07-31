"""Shared local/remote image proxy helpers for channel logos and VOD art."""

from __future__ import annotations

import logging
import mimetypes
import os
import time

import requests
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.utils.http import http_date

from core.models import CoreSettings
from core.utils import resolve_safe_local_data_path

logger = logging.getLogger(__name__)

# Negative cache for remote image URLs that failed to fetch.
# Shared across channel logos and VOD image/logo proxies.
image_fetch_failures = {}
IMAGE_FETCH_FAIL_TTL = 300  # seconds
IMAGE_FETCH_TOTAL_TIMEOUT = 10  # seconds
IMAGE_FETCH_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def _remember_fetch_failure(url: str, failure_cache: dict, fail_ttl: int) -> None:
    now = time.monotonic()
    failure_cache[url] = now + fail_ttl
    if len(failure_cache) > 256:
        for key in [k for k, expiry in failure_cache.items() if expiry <= now]:
            failure_cache.pop(key, None)


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
        remote_response = requests.get(
            url,
            stream=True,
            timeout=(3, 5),
            headers={"User-Agent": CoreSettings.get_default_user_agent()},
        )

        if remote_response.status_code != 200:
            remote_response.close()
            _remember_fetch_failure(url, failure_cache, fail_ttl)
            raise Http404("Remote image not found")

        try:
            chunks = []
            total = 0
            deadline = time.monotonic() + IMAGE_FETCH_TOTAL_TIMEOUT
            for chunk in remote_response.iter_content(chunk_size=8192):
                total += len(chunk)
                if total > IMAGE_FETCH_MAX_BYTES:
                    raise Http404("Remote image too large")
                if time.monotonic() > deadline:
                    _remember_fetch_failure(url, failure_cache, fail_ttl)
                    raise Http404("Remote image fetch timed out")
                chunks.append(chunk)
            body = b"".join(chunks)
        finally:
            remote_response.close()

        failure_cache.pop(url, None)

        content_type = remote_response.headers.get("Content-Type")
        if not content_type:
            content_type, _ = mimetypes.guess_type(url)
        if not content_type:
            content_type = "image/jpeg"

        response = HttpResponse(body, content_type=content_type)
        response["Content-Length"] = str(len(body))
        if remote_response.headers.get("Cache-Control"):
            response["Cache-Control"] = remote_response.headers.get("Cache-Control")
        if remote_response.headers.get("Last-Modified"):
            response["Last-Modified"] = remote_response.headers.get("Last-Modified")
        response["Content-Disposition"] = 'inline; filename="{}"'.format(
            os.path.basename(url.split("?", 1)[0]) or "image"
        )
        return response
    except requests.exceptions.RequestException as e:
        _remember_fetch_failure(url, failure_cache, fail_ttl)
        logger.warning("Error fetching remote %s %s: %s", log_label, url, e)
        raise Http404("Error fetching remote image") from e
