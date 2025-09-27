from __future__ import annotations

import json
from pathlib import Path

from django.http import FileResponse, Http404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser

from core.models import CoreSettings

from .models import BackupJob
from .serializers import BackupJobSerializer, BackupSettingsSerializer
from .tasks import run_backup_task, run_restore_task
from . import services


class BackupJobViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = BackupJobSerializer
    permission_classes = [IsAdminUser]
    queryset = BackupJob.objects.order_by("-created_at")

    def create(self, request, *args, **kwargs):
        job = BackupJob.objects.create(
            job_type=BackupJob.JobType.BACKUP,
            status=BackupJob.Status.PENDING,
            scheduled=False,
            requested_by=request.user if request.user.is_authenticated else None,
        )
        async_result = run_backup_task.apply_async(args=[job.id], kwargs={"scheduled": False})
        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])
        serializer = self.get_serializer(job)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"], url_path="download")
    def download_archive(self, request, pk=None):
        job = self.get_object()
        if job.job_type != BackupJob.JobType.BACKUP:
            return Response({"detail": "Only backup jobs have downloadable archives."}, status=status.HTTP_400_BAD_REQUEST)
        path = job.archive_path
        if not path or not path.exists():
            raise Http404("Backup file not found")
        if job.status != BackupJob.Status.SUCCEEDED:
            return Response({"detail": "Backup not complete."}, status=status.HTTP_400_BAD_REQUEST)
        response = FileResponse(open(path, "rb"), as_attachment=True, filename=job.file_name)
        return response

    @action(detail=True, methods=["post"], url_path="restore")
    def restore_backup(self, request, pk=None):
        job = self.get_object()
        if job.job_type != BackupJob.JobType.BACKUP:
            return Response({"detail": "Only backup jobs can be restored."}, status=status.HTTP_400_BAD_REQUEST)
        if job.status != BackupJob.Status.SUCCEEDED:
            return Response({"detail": "Only successful backups can be restored."}, status=status.HTTP_400_BAD_REQUEST)
        restore_job = BackupJob.objects.create(
            job_type=BackupJob.JobType.RESTORE,
            status=BackupJob.Status.PENDING,
            scheduled=False,
            requested_by=request.user if request.user.is_authenticated else None,
            file_path=job.file_path,
            original_filename=job.file_name,
        )
        async_result = run_restore_task.apply_async(args=[restore_job.id])
        restore_job.celery_task_id = async_result.id
        restore_job.save(update_fields=["celery_task_id", "updated_at"])
        serializer = self.get_serializer(restore_job)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["post"], url_path="restore-upload", parser_classes=[MultiPartParser, FormParser])
    def upload_and_restore(self, request):
        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response({"detail": "No archive uploaded."}, status=status.HTTP_400_BAD_REQUEST)

        backup_root = services.get_configured_backup_root()
        temp_name = uploaded.name or "uploaded-backup.tar.gz"
        original = Path(temp_name)
        suffix = "".join(original.suffixes)
        stem = original.name[: -len(suffix)] if suffix else original.name
        destination = backup_root / (stem + suffix)
        counter = 1
        while destination.exists():
            destination = backup_root / f"{stem}-{counter}{suffix}"
            counter += 1

        with destination.open("wb") as handle:
            for chunk in uploaded.chunks():
                handle.write(chunk)

        restore_job = BackupJob.objects.create(
            job_type=BackupJob.JobType.RESTORE,
            status=BackupJob.Status.PENDING,
            scheduled=False,
            requested_by=request.user if request.user.is_authenticated else None,
            file_path=destination.name,
            original_filename=uploaded.name,
        )
        async_result = run_restore_task.apply_async(args=[restore_job.id])
        restore_job.celery_task_id = async_result.id
        restore_job.save(update_fields=["celery_task_id", "updated_at"])

        serializer = self.get_serializer(restore_job)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_job(self, request, pk=None):
        job = self.get_object()
        if not job.can_cancel:
            return Response({"detail": "This job cannot be canceled."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            async_result = run_backup_task.AsyncResult(job.celery_task_id)
            async_result.revoke(terminate=True)
        except Exception as exc:  # pragma: no cover
            return Response({"detail": f"Failed to cancel job: {exc}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        job.delete_archive()
        job.mark_canceled()
        serializer = self.get_serializer(job)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        job = self.get_object()
        if job.status == BackupJob.Status.RUNNING:
            return Response({"detail": "Running jobs cannot be deleted."}, status=status.HTTP_400_BAD_REQUEST)
        job.delete_archive()
        job.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BackupSettingsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        payload = {
            "enabled": CoreSettings.get_backup_enabled(),
            "retention": CoreSettings.get_backup_retention_count(),
            "path": CoreSettings.get_backup_path() or str(services.get_configured_backup_root()),
            "extra_paths": CoreSettings.get_backup_extra_paths(),
            "include_recordings": CoreSettings.get_backup_include_recordings(),
            "schedule": CoreSettings.get_backup_schedule(),
        }
        return Response(payload)

    def put(self, request):
        serializer = BackupSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        CoreSettings.set_backup_enabled(data["enabled"])
        CoreSettings.set_backup_retention_count(data["retention"])
        CoreSettings.set_backup_path(data["path"])
        try:
            CoreSettings.set_backup_extra_paths(data.get("extra_paths", []))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if "include_recordings" in data:
            CoreSettings.set_backup_include_recordings(data.get("include_recordings", True))

        CoreSettings.set_backup_schedule(data["schedule"])

        services.sync_backup_schedule()

        payload = {
            "enabled": CoreSettings.get_backup_enabled(),
            "retention": CoreSettings.get_backup_retention_count(),
            "path": CoreSettings.get_backup_path(),
            "extra_paths": CoreSettings.get_backup_extra_paths(),
            "include_recordings": CoreSettings.get_backup_include_recordings(),
            "schedule": CoreSettings.get_backup_schedule(),
        }
        return Response(payload, status=status.HTTP_200_OK)
