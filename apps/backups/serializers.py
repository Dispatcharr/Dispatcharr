from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from rest_framework import serializers

from .models import BackupJob

NUMERIC_CRON_PART = r"^[\d*/,\-]+$"
ALPHA_NUMERIC_CRON_PART = r"^[\da-zA-Z*/,\-]+$"
SCHEDULE_PRESETS = ("hourly", "daily", "weekly", "monthly", "custom")


class BackupJobSerializer(serializers.ModelSerializer):
    requested_by = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    can_download = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = BackupJob
        fields = [
            "id",
            "job_type",
            "status",
            "scheduled",
            "requested_by",
            "file_path",
            "file_name",
            "file_size",
            "original_filename",
            "celery_task_id",
            "error_message",
            "created_at",
            "updated_at",
            "completed_at",
            "can_download",
            "can_cancel",
            "can_delete",
        ]
        read_only_fields = [
            "job_type",
            "status",
            "scheduled",
            "requested_by",
            "file_path",
            "file_name",
            "file_size",
            "original_filename",
            "celery_task_id",
            "error_message",
            "created_at",
            "updated_at",
            "completed_at",
            "can_download",
            "can_cancel",
            "can_delete",
        ]

    def get_requested_by(self, obj: BackupJob) -> str | None:
        if obj.requested_by:
            return obj.requested_by.username
        return None

    def get_file_name(self, obj: BackupJob) -> str:
        return obj.file_name

    def get_can_download(self, obj: BackupJob) -> bool:
        return obj.status == BackupJob.Status.SUCCEEDED and obj.job_type == BackupJob.JobType.BACKUP

    def get_can_cancel(self, obj: BackupJob) -> bool:
        return obj.can_cancel

    def get_can_delete(self, obj: BackupJob) -> bool:
        return obj.can_delete


class BackupScheduleSerializer(serializers.Serializer):
    preset = serializers.ChoiceField(choices=[(preset, preset.title()) for preset in SCHEDULE_PRESETS])
    minute = serializers.RegexField(NUMERIC_CRON_PART)
    hour = serializers.RegexField(NUMERIC_CRON_PART)
    day_of_month = serializers.RegexField(NUMERIC_CRON_PART)
    month = serializers.RegexField(ALPHA_NUMERIC_CRON_PART)
    day_of_week = serializers.RegexField(ALPHA_NUMERIC_CRON_PART)
    timezone = serializers.CharField(required=False)

    def validate_timezone(self, value: str) -> str:
        if not value:
            return getattr(settings, "TIME_ZONE", "UTC")
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise serializers.ValidationError("Unknown timezone") from exc
        return value


class BackupSettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    retention = serializers.IntegerField(min_value=0)
    path = serializers.CharField(max_length=1024)
    extra_paths = serializers.ListField(child=serializers.CharField(max_length=1024), required=False, allow_empty=True)
    include_recordings = serializers.BooleanField(required=False)
    schedule = BackupScheduleSerializer()

    def validate_path(self, value: str) -> str:
        if not value:
            raise serializers.ValidationError("Backup path cannot be blank")
        target = Path(value)
        if not target.is_absolute():
            base = getattr(settings, "BACKUP_ROOT", settings.BASE_DIR)
            target = (Path(base) / target).resolve()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise serializers.ValidationError(f"Unable to access backup path: {exc}") from exc
        return str(value)

    def validate_extra_paths(self, value):
        cleaned = []
        for entry in value:
            if not entry:
                continue
            cleaned.append(entry)
        return cleaned

    def validate(self, attrs):
        schedule = attrs.get("schedule") or {}
        if not schedule:
            raise serializers.ValidationError({"schedule": "Schedule is required."})
        return attrs
