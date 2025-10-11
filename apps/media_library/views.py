import logging
import mimetypes
import os
import re

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    StreamingHttpResponse,
)
from django.views.decorators.http import require_GET

from apps.media_library.models import MediaFile
from apps.media_library.transcode import start_streaming_transcode

logger = logging.getLogger(__name__)

STREAM_SIGNER = TimestampSigner(salt="media-library-stream")
TOKEN_TTL = getattr(settings, "MEDIA_LIBRARY_STREAM_TOKEN_TTL", 3600)

mimetypes.add_type("video/x-matroska", ".mkv", strict=False)


def _iter_file(file_obj, offset=0, length=None, chunk_size=8192):
    file_obj.seek(offset)
    remaining = length
    while True:
        if remaining is not None and remaining <= 0:
            break
        read_size = chunk_size if remaining is None else min(chunk_size, remaining)
        data = file_obj.read(read_size)
        if not data:
            break
        if remaining is not None:
            remaining -= len(data)
        yield data


def _guess_mime(path: str | None) -> str:
    if not path:
        return "application/octet-stream"
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


@require_GET
def stream_media_file(request, token: str):
    try:
        payload = STREAM_SIGNER.unsign_object(token, max_age=TOKEN_TTL)
    except SignatureExpired:
        return HttpResponseForbidden("Stream link expired")
    except BadSignature:
        raise Http404("Invalid stream token")

    file_id = payload.get("file_id")
    user_id = payload.get("user_id")

    if request.user.is_authenticated and request.user.id != user_id:
        return HttpResponseForbidden("Stream token not issued for this user")

    start_ms = payload.get("start_ms", 0)
    try:
        start_ms = int(start_ms)
    except (TypeError, ValueError):
        start_ms = 0
    start_seconds = max(0.0, start_ms / 1000.0)

    try:
        media_file = MediaFile.objects.get(pk=file_id)
    except MediaFile.DoesNotExist:
        raise Http404("Media file not found")

    duration_seconds: float | None = None
    duration_ms = media_file.effective_duration_ms
    if duration_ms:
        try:
            duration_seconds = float(duration_ms) / 1000.0
        except (TypeError, ValueError):
            duration_seconds = None

    original_path = media_file.absolute_path or ""
    cached_path = media_file.transcoded_path or ""

    playback_path = ""
    mime_type = "application/octet-stream"
    download_name = media_file.file_name or f"{media_file.id}.mp4"

    if cached_path and os.path.exists(cached_path):
        playback_path = cached_path
        mime_type = media_file.transcoded_mime_type or "video/mp4"
        base_name, _ = os.path.splitext(media_file.file_name or "")
        download_name = f"{base_name or media_file.id}.mp4"
    else:
        if cached_path and media_file.transcode_status == MediaFile.TRANSCODE_STATUS_READY:
            # Cached entry missing on disk – reset so we regenerate.
            media_file.transcode_status = MediaFile.TRANSCODE_STATUS_PENDING
            media_file.transcoded_path = ""
            media_file.transcoded_mime_type = ""
            media_file.transcoded_at = None
            media_file.save(
                update_fields=[
                    "transcode_status",
                    "transcoded_path",
                    "transcoded_mime_type",
                    "transcoded_at",
                    "updated_at",
                ]
            )

        if original_path and os.path.exists(original_path) and media_file.is_browser_playable():
            playback_path = original_path
            mime_type = _guess_mime(original_path)
            download_name = media_file.file_name or os.path.basename(original_path)
        elif original_path and os.path.exists(original_path):
            # Start live transcode and stream output directly.
            try:
                session = start_streaming_transcode(
                    media_file,
                    start_seconds=start_seconds,
                )
            except FileNotFoundError:
                raise Http404("Media file not found")
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Unable to start live transcode for media file %s: %s",
                    media_file.id,
                    exc,
                    exc_info=True,
                )
                return HttpResponse(
                    "Unable to prepare video for playback. Please try again later.",
                    status=500,
                )

            base_name, _ = os.path.splitext(media_file.file_name or "")
            download_name = f"{base_name or media_file.id}.mp4"

            response = StreamingHttpResponse(
                session.stream(),
                content_type=session.mime_type,
            )
            response["Content-Disposition"] = f'inline; filename="{download_name}"'
            response["Cache-Control"] = "no-store"
            response["Accept-Ranges"] = "none"
            if duration_seconds:
                formatted_duration = f"{duration_seconds:.3f}"
                response["X-Content-Duration"] = formatted_duration
                response["Content-Duration"] = formatted_duration
            return response
        else:
            raise Http404("Media file not found")

    if not playback_path or not os.path.exists(playback_path):
        raise Http404("Media file not found")

    file_size = os.path.getsize(playback_path)
    mime_type = mime_type or _guess_mime(playback_path)

    range_header = request.headers.get("Range")
    if range_header:
        range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if range_match:
            start = int(range_match.group(1))
            end_raw = range_match.group(2)
            end = int(end_raw) if end_raw else file_size - 1
            if start >= file_size:
                response = HttpResponse(status=416)
                response["Content-Range"] = f"bytes */{file_size}"
                return response
            end = min(end, file_size - 1)
            length = end - start + 1

            file_handle = open(playback_path, "rb")

            def closing_iterator():
                try:
                    yield from _iter_file(file_handle, offset=start, length=length)
                finally:
                    file_handle.close()

            response = StreamingHttpResponse(
                closing_iterator(), status=206, content_type=mime_type
            )
            response["Content-Length"] = str(length)
            response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            response["Accept-Ranges"] = "bytes"
            response["Content-Disposition"] = (
                f'inline; filename="{download_name}"'
            )
            if duration_seconds:
                formatted_duration = f"{duration_seconds:.3f}"
                response["X-Content-Duration"] = formatted_duration
                response["Content-Duration"] = formatted_duration
            return response

    response = FileResponse(open(playback_path, "rb"), content_type=mime_type)
    response["Accept-Ranges"] = "bytes"
    response["Content-Length"] = str(file_size)
    response["Content-Disposition"] = (
        f'inline; filename="{download_name}"'
    )
    if duration_seconds:
        formatted_duration = f"{duration_seconds:.3f}"
        response["X-Content-Duration"] = formatted_duration
        response["Content-Duration"] = formatted_duration
    return response
