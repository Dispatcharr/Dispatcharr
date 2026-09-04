"""Browse/view/download the persisted log files in LOG_FILE_DIR (System > Logs).
Admin-only: log lines can reference provider URLs and account names.
"""

import os
import re
from datetime import datetime, timezone

from django.conf import settings
from django.http import FileResponse, HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.accounts.permissions import IsAdmin
from dispatcharr.log_collector import collector_running

# Plain filenames only: no separators, no dotfiles.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# The only family these endpoints serve: the live log and its rotations.
LOG_NAME_PREFIX = "dispatcharr.log"

# Inline viewing serves this many trailing bytes; download streams the whole file.
MAX_VIEW_BYTES = 5 * 1024 * 1024


def _log_dir():
    return getattr(settings, "LOG_FILE_DIR", None) or "/data/logs"


def _resolve(name):
    """Resolve *name* to a real log file inside the log directory, else None."""
    # Checked here, not only in the listing: DISPATCHARR_LOG_DIR may hold more than logs.
    if not _NAME_RE.match(name) or not name.startswith(LOG_NAME_PREFIX):
        return None
    base = os.path.realpath(_log_dir())
    path = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(path) != base or not os.path.isfile(path):
        return None
    return path


@api_view(["GET"])
@permission_classes([IsAdmin])
def list_log_files(request):
    base = _log_dir()
    files = []
    try:
        names = os.listdir(base)
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
    files.sort(key=lambda f: f["modified"], reverse=True)
    return Response(
        {
            "path": base,
            "files": files,
            "collector_running": collector_running(base),
        }
    )


@api_view(["GET"])
@permission_classes([IsAdmin])
def get_log_file(request, name):
    path = _resolve(name)
    if path is None:
        raise NotFound("Log file not found")

    with open(path, "rb") as f:
        # Size comes from the open handle, so a rotation cannot land between
        # the two and leave us seeking past the end of a fresh, empty file.
        size = os.fstat(f.fileno()).st_size
        truncated = size > MAX_VIEW_BYTES
        if truncated:
            f.seek(size - MAX_VIEW_BYTES)
            data = f.read(MAX_VIEW_BYTES)
            # Start at a line boundary so the client never sees a torn line.
            newline = data.find(b"\n")
            if newline >= 0:
                data = data[newline + 1 :]
        else:
            data = f.read()
    response = HttpResponse(data, content_type="text/plain; charset=utf-8")
    response["X-Log-Truncated"] = "1" if truncated else "0"
    return response


@api_view(["GET"])
@permission_classes([IsAdmin])
def download_log_file(request, name):
    """Stream a log file as an attachment over the authenticated session."""
    path = _resolve(name)
    if path is None:
        raise NotFound("Log file not found")

    response = FileResponse(
        open(path, "rb"), content_type="text/plain; charset=utf-8"
    )
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response
