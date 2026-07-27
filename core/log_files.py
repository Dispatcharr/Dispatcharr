"""Browse/view/download the persisted log files in LOG_FILE_DIR (System > Logs).
Admin-only: log lines can reference provider URLs and account names.
"""

import hashlib
import hmac
import os
import re
from datetime import datetime, timezone

from django.conf import settings
from django.http import FileResponse, HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.permissions import IsAdmin

# Plain filenames only: no separators, no dotfiles, nothing path-like.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Inline viewing serves at most this many trailing bytes; Download always
# streams the whole file.
MAX_VIEW_BYTES = 5 * 1024 * 1024


def _log_dir():
    return getattr(settings, "LOG_FILE_DIR", None) or "/data/logs"


def _resolve(name):
    """Resolve *name* to a real file inside the log directory, else None."""
    # NOTE: stricter than core.utils.resolve_safe_local_data_path (exact dirname match, not a prefix check).
    if not _NAME_RE.match(name):
        return None
    base = os.path.realpath(_log_dir())
    path = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(path) != base or not os.path.isfile(path):
        return None
    return path


def _download_token(name):
    """Signed token letting a plain link download *name* without the JWT."""
    return hmac.new(
        settings.SECRET_KEY.encode(), name.encode(), hashlib.sha256
    ).hexdigest()[:32]


def _verify_download_token(name, token):
    return hmac.compare_digest(_download_token(name), token)


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
        # Resolve through the same realpath-containment gate as view/download, so a symlink escaping the dir is never even listed.
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
    return Response({"path": base, "files": files})


@api_view(["GET"])
@permission_classes([IsAdmin])
def get_log_file(request, name):
    path = _resolve(name)
    if path is None:
        raise NotFound("Log file not found")

    size = os.path.getsize(path)
    truncated = size > MAX_VIEW_BYTES
    with open(path, "rb") as f:
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
def get_log_download_token(request, name):
    """Mint a signed token for downloading *name* over a plain link."""
    path = _resolve(name)
    if path is None:
        raise NotFound("Log file not found")
    return Response({"token": _download_token(name)})


@api_view(["GET"])
@permission_classes([AllowAny])
def download_log_file(request, name):
    """Stream a log file as an attachment; requires a signed ``token`` param or admin auth."""
    token = request.query_params.get("token")
    if token:
        if not _verify_download_token(name, token):
            return Response({"detail": "Invalid download token"}, status=403)
    else:
        if not (
            request.user.is_authenticated
            and getattr(request.user, "user_level", 0) >= 10
        ):
            return Response({"detail": "Authentication required"}, status=401)

    path = _resolve(name)
    if path is None:
        raise NotFound("Log file not found")

    response = FileResponse(
        open(path, "rb"), content_type="text/plain; charset=utf-8"
    )
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response
