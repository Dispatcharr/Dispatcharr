import json
import logging

from django_celery_beat.models import PeriodicTask

from core.models import CoreSettings
from core.scheduling import (
    create_or_update_periodic_task,
    delete_periodic_task,
)

logger = logging.getLogger(__name__)

BACKUP_SCHEDULE_TASK_NAME = "backup-scheduled-task"

DEFAULTS = {
    "schedule_enabled": True,
    "schedule_frequency": "daily",
    "schedule_time": "03:00",
    "schedule_day_of_week": 0,  # Sunday
    "retention_count": 3,
    "schedule_cron_expression": "",
}


def _get_backup_settings():
    """Get all backup settings from CoreSettings grouped JSON."""
    try:
        settings_obj = CoreSettings.objects.get(key="backup_settings")
        return settings_obj.value if isinstance(settings_obj.value, dict) else DEFAULTS.copy()
    except CoreSettings.DoesNotExist:
        return DEFAULTS.copy()


def _update_backup_settings(updates: dict) -> None:
    """Update backup settings in the grouped JSON."""
    obj, created = CoreSettings.objects.get_or_create(
        key="backup_settings",
        defaults={"name": "Backup Settings", "value": DEFAULTS.copy()}
    )
    current = obj.value if isinstance(obj.value, dict) else {}
    current.update(updates)
    obj.value = current
    obj.save()


def get_schedule_settings() -> dict:
    """Get all backup schedule settings."""
    settings = _get_backup_settings()
    return {
        "enabled": bool(settings.get("schedule_enabled", DEFAULTS["schedule_enabled"])),
        "frequency": str(settings.get("schedule_frequency", DEFAULTS["schedule_frequency"])),
        "time": str(settings.get("schedule_time", DEFAULTS["schedule_time"])),
        "day_of_week": int(settings.get("schedule_day_of_week", DEFAULTS["schedule_day_of_week"])),
        "retention_count": int(settings.get("retention_count", DEFAULTS["retention_count"])),
        "cron_expression": str(settings.get("schedule_cron_expression", DEFAULTS["schedule_cron_expression"])),
    }


def update_schedule_settings(data: dict) -> dict:
    """Update backup schedule settings and sync the PeriodicTask."""
    # Validate
    if "frequency" in data and data["frequency"] not in ("daily", "weekly"):
        raise ValueError("frequency must be 'daily' or 'weekly'")

    if "time" in data:
        try:
            hour, minute = data["time"].split(":")
            int(hour)
            int(minute)
        except (ValueError, AttributeError):
            raise ValueError("time must be in HH:MM format")

    if "day_of_week" in data:
        day = int(data["day_of_week"])
        if day < 0 or day > 6:
            raise ValueError("day_of_week must be 0-6 (Sunday-Saturday)")

    if "retention_count" in data:
        count = int(data["retention_count"])
        if count < 0:
            raise ValueError("retention_count must be >= 0")

    # Update settings with proper key names
    updates = {}
    if "enabled" in data:
        updates["schedule_enabled"] = bool(data["enabled"])
    if "frequency" in data:
        updates["schedule_frequency"] = str(data["frequency"])
    if "time" in data:
        updates["schedule_time"] = str(data["time"])
    if "day_of_week" in data:
        updates["schedule_day_of_week"] = int(data["day_of_week"])
    if "retention_count" in data:
        updates["retention_count"] = int(data["retention_count"])
    if "cron_expression" in data:
        updates["schedule_cron_expression"] = str(data["cron_expression"])

    _update_backup_settings(updates)

    # Sync the periodic task
    _sync_periodic_task()

    return get_schedule_settings()


def _sync_periodic_task() -> None:
    """Create, update, or delete the scheduled backup task based on settings."""
    settings = get_schedule_settings()

    if not settings["enabled"]:
        delete_periodic_task(BACKUP_SCHEDULE_TASK_NAME)
        logger.info("Backup schedule disabled, removed periodic task")
        return

    # Check if using cron expression (advanced mode)
    if settings["cron_expression"]:
        cron_expr = settings["cron_expression"]
    else:
        # Build a cron expression from simple frequency settings
        hour, minute = settings["time"].split(":")
        if settings["frequency"] == "daily":
            cron_expr = f"{minute} {hour} * * *"
        else:  # weekly
            cron_expr = f"{minute} {hour} * * {settings['day_of_week']}"

    create_or_update_periodic_task(
        task_name=BACKUP_SCHEDULE_TASK_NAME,
        celery_task_path="apps.backups.tasks.scheduled_backup_task",
        kwargs={"retention_count": settings["retention_count"]},
        cron_expression=cron_expr,
        enabled=True,
    )
