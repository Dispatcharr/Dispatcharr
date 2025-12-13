import json
import logging

from django_celery_beat.models import PeriodicTask, CrontabSchedule

from core.models import CoreSettings

logger = logging.getLogger(__name__)

BACKUP_SCHEDULE_TASK_NAME = "backup-scheduled-task"

SETTING_KEYS = {
    "enabled": "backup_schedule_enabled",
    "frequency": "backup_schedule_frequency",
    "time": "backup_schedule_time",
    "day_of_week": "backup_schedule_day_of_week",
    "retention_count": "backup_retention_count",
    "cron_expression": "backup_schedule_cron_expression",
}

DEFAULTS = {
    "enabled": False,
    "frequency": "daily",
    "time": "03:00",
    "day_of_week": 0,  # Sunday
    "retention_count": 0,
    "cron_expression": "",
}


def _get_setting(key: str, default=None):
    """Get a backup setting from CoreSettings."""
    try:
        setting = CoreSettings.objects.get(key=SETTING_KEYS[key])
        value = setting.value
        if key == "enabled":
            return value.lower() == "true"
        elif key in ("day_of_week", "retention_count"):
            return int(value)
        return value
    except CoreSettings.DoesNotExist:
        return default if default is not None else DEFAULTS.get(key)


def _set_setting(key: str, value) -> None:
    """Set a backup setting in CoreSettings."""
    str_value = str(value).lower() if isinstance(value, bool) else str(value)
    CoreSettings.objects.update_or_create(
        key=SETTING_KEYS[key],
        defaults={
            "name": f"Backup {key.replace('_', ' ').title()}",
            "value": str_value,
        },
    )


def get_schedule_settings() -> dict:
    """Get all backup schedule settings."""
    return {
        "enabled": _get_setting("enabled"),
        "frequency": _get_setting("frequency"),
        "time": _get_setting("time"),
        "day_of_week": _get_setting("day_of_week"),
        "retention_count": _get_setting("retention_count"),
        "cron_expression": _get_setting("cron_expression"),
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

    # Update settings
    for key in ("enabled", "frequency", "time", "day_of_week", "retention_count", "cron_expression"):
        if key in data:
            _set_setting(key, data[key])

    # Sync the periodic task
    _sync_periodic_task()

    return get_schedule_settings()


def _sync_periodic_task() -> None:
    """Create, update, or delete the scheduled backup task based on settings."""
    settings = get_schedule_settings()

    if not settings["enabled"]:
        # Delete the task if it exists
        PeriodicTask.objects.filter(name=BACKUP_SCHEDULE_TASK_NAME).delete()
        logger.info("Backup schedule disabled, removed periodic task")
        return

    # Check if using cron expression (advanced mode)
    if settings["cron_expression"]:
        # Parse cron expression: "minute hour day month weekday"
        try:
            parts = settings["cron_expression"].split()
            if len(parts) != 5:
                raise ValueError("Cron expression must have 5 parts: minute hour day month weekday")

            minute, hour, day_of_month, month_of_year, day_of_week = parts

            crontab, _ = CrontabSchedule.objects.get_or_create(
                minute=minute,
                hour=hour,
                day_of_week=day_of_week,
                day_of_month=day_of_month,
                month_of_year=month_of_year,
                timezone=CoreSettings.get_system_time_zone(),
            )
        except Exception as e:
            logger.error(f"Invalid cron expression '{settings['cron_expression']}': {e}")
            raise ValueError(f"Invalid cron expression: {e}")
    else:
        # Use simple frequency-based scheduling
        # Parse time
        hour, minute = settings["time"].split(":")

        # Build crontab based on frequency
        system_tz = CoreSettings.get_system_time_zone()
        if settings["frequency"] == "daily":
            crontab, _ = CrontabSchedule.objects.get_or_create(
                minute=minute,
                hour=hour,
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
                timezone=system_tz,
            )
        else:  # weekly
            crontab, _ = CrontabSchedule.objects.get_or_create(
                minute=minute,
                hour=hour,
                day_of_week=str(settings["day_of_week"]),
                day_of_month="*",
                month_of_year="*",
                timezone=system_tz,
            )

    # Create or update the periodic task
    task, created = PeriodicTask.objects.update_or_create(
        name=BACKUP_SCHEDULE_TASK_NAME,
        defaults={
            "task": "apps.backups.tasks.scheduled_backup_task",
            "crontab": crontab,
            "enabled": True,
            "kwargs": json.dumps({"retention_count": settings["retention_count"]}),
        },
    )

    action = "Created" if created else "Updated"
    logger.info(f"{action} backup schedule: {settings['frequency']} at {settings['time']}")
