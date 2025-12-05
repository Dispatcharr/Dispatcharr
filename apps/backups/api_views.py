import hashlib
import hmac
import logging
import os
from pathlib import Path

from celery.result import AsyncResult
from django.conf import settings
from django.http import HttpResponse, StreamingHttpResponse, Http404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAdminUser, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from . import services
from .tasks import create_backup_task, restore_backup_task
from .scheduler import get_schedule_settings, update_schedule_settings

logger = logging.getLogger(__name__)


def _generate_task_token(task_id: str) -> str:
    """Generate a signed token for task status access without auth."""
    secret = settings.SECRET_KEY.encode()
    return hmac.new(secret, task_id.encode(), hashlib.sha256).hexdigest()[:32]


def _verify_task_token(task_id: str, token: str) -> bool:
    """Verify a task token is valid."""
    expected = _generate_task_token(task_id)
    return hmac.compare_digest(expected, token)


@api_view(["GET"])
@permission_classes([IsAdminUser])
def list_backups(request):
    """List all available backup files."""
    try:
        backups = services.list_backups()
        return Response(backups, status=status.HTTP_200_OK)
    except Exception as e:
        return Response(
            {"detail": f"Failed to list backups: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAdminUser])
def create_backup(request):
    """Create a new backup (async via Celery)."""
    try:
        task = create_backup_task.delay()
        return Response(
            {
                "detail": "Backup started",
                "task_id": task.id,
                "task_token": _generate_task_token(task.id),
            },
            status=status.HTTP_202_ACCEPTED,
        )
    except Exception as e:
        return Response(
            {"detail": f"Failed to start backup: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def backup_status(request, task_id):
    """Check the status of a backup/restore task.

    Requires either:
    - Valid admin authentication, OR
    - Valid task_token query parameter
    """
    # Check for token-based auth (for restore when session is invalidated)
    token = request.query_params.get("token")
    if token:
        if not _verify_task_token(task_id, token):
            return Response(
                {"detail": "Invalid task token"},
                status=status.HTTP_403_FORBIDDEN,
            )
    else:
        # Fall back to admin auth check
        if not request.user.is_authenticated or not request.user.is_staff:
            return Response(
                {"detail": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

    try:
        result = AsyncResult(task_id)

        if result.ready():
            task_result = result.get()
            if task_result.get("status") == "completed":
                return Response({
                    "state": "completed",
                    "result": task_result,
                })
            else:
                return Response({
                    "state": "failed",
                    "error": task_result.get("error", "Unknown error"),
                })
        elif result.failed():
            return Response({
                "state": "failed",
                "error": str(result.result),
            })
        else:
            return Response({
                "state": result.state.lower(),
            })
    except Exception as e:
        return Response(
            {"detail": f"Failed to get task status: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAdminUser])
def get_download_token(request, filename):
    """Get a signed token for downloading a backup file."""
    try:
        # Security: prevent path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            raise Http404("Invalid filename")

        backup_dir = services.get_backup_dir()
        backup_file = backup_dir / filename

        if not backup_file.exists():
            raise Http404("Backup file not found")

        token = _generate_task_token(filename)
        return Response({"token": token})
    except Http404:
        raise
    except Exception as e:
        return Response(
            {"detail": f"Failed to generate token: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def download_backup(request, filename):
    """Download a backup file.

    Requires either:
    - Valid admin authentication, OR
    - Valid download_token query parameter
    """
    # Check for token-based auth (avoids CORS preflight issues)
    token = request.query_params.get("token")
    if token:
        if not _verify_task_token(filename, token):
            return Response(
                {"detail": "Invalid download token"},
                status=status.HTTP_403_FORBIDDEN,
            )
    else:
        # Fall back to admin auth check
        if not request.user.is_authenticated or not request.user.is_staff:
            return Response(
                {"detail": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

    try:
        # Security: prevent path traversal by checking for suspicious characters
        if ".." in filename or "/" in filename or "\\" in filename:
            raise Http404("Invalid filename")

        backup_dir = services.get_backup_dir()
        backup_file = (backup_dir / filename).resolve()

        # Security: ensure the resolved path is still within backup_dir
        if not str(backup_file).startswith(str(backup_dir.resolve())):
            raise Http404("Invalid filename")

        if not backup_file.exists() or not backup_file.is_file():
            raise Http404("Backup file not found")

        file_size = backup_file.stat().st_size

        # Use X-Accel-Redirect for nginx (AIO container) - nginx serves file directly
        # Fall back to streaming for non-nginx deployments
        use_nginx_accel = os.environ.get("USE_NGINX_ACCEL", "").lower() == "true"
        logger.info(f"[DOWNLOAD] File: {filename}, Size: {file_size}, USE_NGINX_ACCEL: {use_nginx_accel}")

        if use_nginx_accel:
            # X-Accel-Redirect: Django returns immediately, nginx serves file
            logger.info(f"[DOWNLOAD] Using X-Accel-Redirect: /protected-backups/{filename}")
            response = HttpResponse()
            response["X-Accel-Redirect"] = f"/protected-backups/{filename}"
            response["Content-Type"] = "application/zip"
            response["Content-Length"] = file_size
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        else:
            # Streaming fallback for non-nginx deployments
            logger.info(f"[DOWNLOAD] Using streaming fallback (no nginx)")
            def file_iterator(file_path, chunk_size=2 * 1024 * 1024):
                with open(file_path, "rb") as f:
                    while chunk := f.read(chunk_size):
                        yield chunk

            response = StreamingHttpResponse(
                file_iterator(backup_file),
                content_type="application/zip",
            )
            response["Content-Length"] = file_size
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
    except Http404:
        raise
    except Exception as e:
        return Response(
            {"detail": f"Download failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["DELETE"])
@permission_classes([IsAdminUser])
def delete_backup(request, filename):
    """Delete a backup file."""
    try:
        # Security: prevent path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            raise Http404("Invalid filename")

        services.delete_backup(filename)
        return Response(
            {"detail": "Backup deleted successfully"},
            status=status.HTTP_204_NO_CONTENT,
        )
    except FileNotFoundError:
        raise Http404("Backup file not found")
    except Exception as e:
        return Response(
            {"detail": f"Delete failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAdminUser])
@parser_classes([MultiPartParser, FormParser])
def upload_backup(request):
    """Upload a backup file for restoration."""
    uploaded = request.FILES.get("file")
    if not uploaded:
        return Response(
            {"detail": "No file uploaded"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        backup_dir = services.get_backup_dir()
        filename = uploaded.name or "uploaded-backup.zip"

        # Ensure unique filename
        backup_file = backup_dir / filename
        counter = 1
        while backup_file.exists():
            name_parts = filename.rsplit(".", 1)
            if len(name_parts) == 2:
                backup_file = backup_dir / f"{name_parts[0]}-{counter}.{name_parts[1]}"
            else:
                backup_file = backup_dir / f"{filename}-{counter}"
            counter += 1

        # Save uploaded file
        with backup_file.open("wb") as f:
            for chunk in uploaded.chunks():
                f.write(chunk)

        return Response(
            {
                "detail": "Backup uploaded successfully",
                "filename": backup_file.name,
            },
            status=status.HTTP_201_CREATED,
        )
    except Exception as e:
        return Response(
            {"detail": f"Upload failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAdminUser])
def restore_backup(request, filename):
    """Restore from a backup file (async via Celery). WARNING: This will flush the database!"""
    try:
        # Security: prevent path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            raise Http404("Invalid filename")

        backup_dir = services.get_backup_dir()
        backup_file = backup_dir / filename

        if not backup_file.exists():
            raise Http404("Backup file not found")

        task = restore_backup_task.delay(filename)
        return Response(
            {
                "detail": "Restore started",
                "task_id": task.id,
                "task_token": _generate_task_token(task.id),
            },
            status=status.HTTP_202_ACCEPTED,
        )
    except Http404:
        raise
    except Exception as e:
        return Response(
            {"detail": f"Failed to start restore: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAdminUser])
def get_schedule(request):
    """Get backup schedule settings."""
    try:
        settings = get_schedule_settings()
        return Response(settings)
    except Exception as e:
        return Response(
            {"detail": f"Failed to get schedule: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["PUT"])
@permission_classes([IsAdminUser])
def update_schedule(request):
    """Update backup schedule settings."""
    try:
        settings = update_schedule_settings(request.data)
        return Response(settings)
    except ValueError as e:
        return Response(
            {"detail": str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        return Response(
            {"detail": f"Failed to update schedule: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
