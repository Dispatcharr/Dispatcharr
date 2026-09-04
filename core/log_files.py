"""Browse/view/download the persisted log files in LOG_FILE_DIR (System > Logs).
Admin-only: log lines can reference provider URLs and account names.
"""

import os
import re
from datetime import datetime, timezone

from django.conf import settings
from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiParameter
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.accounts.permissions import IsAdmin
from dispatcharr.log_collector import BASE_NAME, collector_running

# Plain filenames only: no separators, no dotfiles.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Inline viewing serves this many trailing bytes; download streams the whole file.
MAX_VIEW_BYTES = 5 * 1024 * 1024


def _open_log(path):
    """Open *path*, mapping a file pruned since resolution to a 404."""
    try:
        return open(path, "rb")
    except FileNotFoundError:
        raise NotFound("Log file not found")


def _at_line_start(f, offset):
    """Whether *offset* sits just past a newline, i.e. begins a record."""
    if offset == 0:
        return True
    f.seek(offset - 1)
    return f.read(1) == b"\n"


def _resolve(name):
    """Resolve *name* to a real log file inside the log directory, else None."""
    # Checked here, not only in the listing: DISPATCHARR_LOG_DIR may hold more than logs.
    log_dir = settings.LOG_FILE_DIR
    if not log_dir or not _NAME_RE.match(name) or not name.startswith(BASE_NAME):
        return None
    base = os.path.realpath(log_dir)
    path = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(path) != base or not os.path.isfile(path):
        return None
    return path


@api_view(["GET"])
@permission_classes([IsAdmin])
def list_log_files(request):
    base = settings.LOG_FILE_DIR
    files = []
    try:
        names = os.listdir(base) if base else []
    except OSError:
        names = []
    for name in names:
        # Same containment gate as view/download: a symlink escaping the dir is never listed.
        path = _resolve(name)
        if path is None:
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        files.append(
            {
                "name": name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    files.sort(key=lambda f: (f["modified"], f["name"]), reverse=True)
    return Response(
        {
            "files": files,
            "collector_running": collector_running(base),
        }
    )


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="cursor",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description=(
                "Opaque position from a previous response's cursor. Serves "
                "only the bytes written past it, unless the file rotated or "
                "the gap exceeds the view cap, in which case the response "
                "resets to a fresh tail."
            ),
        ),
    ],
    responses={
        200: inline_serializer(
            name="LogTail",
            fields={
                "content": serializers.CharField(),
                "cursor": serializers.CharField(),
                "reset": serializers.BooleanField(),
                "truncated": serializers.BooleanField(),
            },
        )
    },
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def get_log_file(request, name):
    path = _resolve(name)
    if path is None:
        raise NotFound("Log file not found")

    cursor = request.GET.get("cursor", "")
    with _open_log(path) as f:
        # Identity and size come from the open handle, so a rotation cannot land
        # between them and leave us seeking past the end of a fresh, empty file.
        stat = os.fstat(f.fileno())
        start, reset = 0, True
        if cursor:
            prev_inode, _, prev_end = cursor.partition("-")
            # A new inode is a rotation: the old offset means nothing in the new
            # file, and resuming at it would skip content or freeze the view.
            valid = len(prev_end) < 20 and prev_end.isdecimal()
            if prev_inode == str(stat.st_ino) and valid:
                offset = int(prev_end)
                # Rotation frees inodes for reuse, so identity alone can be
                # fooled; an offset mid-line did not come from this file.
                if _at_line_start(f, offset):
                    start, reset = offset, False
        # A tab that slept asks for more than we serve; fall back to the tail.
        truncated = stat.st_size - start > MAX_VIEW_BYTES
        if truncated:
            start, reset = stat.st_size - MAX_VIEW_BYTES, True
        f.seek(start)
        # Bounded by the size this handle reported, so concurrent appends
        # cannot push the body past the cap the response advertises.
        data = f.read(stat.st_size - start)

    if reset and start:
        # Start at a line boundary so the client never sees a torn line.
        newline = data.find(b"\n")
        if newline >= 0:
            start += newline + 1
            data = data[newline + 1 :]
    # Mid-write, the tail is a fragment; it arrives whole on the next poll.
    end = data.rfind(b"\n")
    data = data[: end + 1] if end >= 0 else b""

    return Response(
        {
            "content": data.decode("utf-8", "replace"),
            "cursor": f"{stat.st_ino}-{start + len(data)}",
            "reset": reset,
            "truncated": truncated,
        }
    )


@api_view(["GET"])
@permission_classes([IsAdmin])
def download_log_file(request, name):
    """Stream a log file as an attachment over the authenticated session."""
    path = _resolve(name)
    if path is None:
        raise NotFound("Log file not found")

    response = FileResponse(
        _open_log(path), content_type="text/plain; charset=utf-8"
    )
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response
