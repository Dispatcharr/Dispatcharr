import json
import logging

from django_celery_beat.models import PeriodicTask, CrontabSchedule

from core.models import CoreSettings

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
        # Delete the task if it exists
        task = PeriodicTask.objects.filter(name=BACKUP_SCHEDULE_TASK_NAME).first()
        if task:
            old_crontab = task.crontab
            task.delete()
            _cleanup_orphaned_crontab(old_crontab)
        logger.info("Backup schedule disabled, removed periodic task")
        return

    # Get old crontab before creating new one
    old_crontab = None
    try:
        old_task = PeriodicTask.objects.get(name=BACKUP_SCHEDULE_TASK_NAME)
        old_crontab = old_task.crontab
    except PeriodicTask.DoesNotExist:
        pass

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

    # Clean up old crontab if it changed and is orphaned
    if old_crontab and old_crontab.id != crontab.id:
        _cleanup_orphaned_crontab(old_crontab)

    action = "Created" if created else "Updated"
    logger.info(f"{action} backup schedule: {settings['frequency']} at {settings['time']}")


def _cleanup_orphaned_crontab(crontab_schedule):
    """Delete old CrontabSchedule if no other tasks are using it."""
    if crontab_schedule is None:
        return

    # Check if any other tasks are using this crontab
    if PeriodicTask.objects.filter(crontab=crontab_schedule).exists():
        logger.debug(f"CrontabSchedule {crontab_schedule.id} still in use, not deleting")
        return

    logger.debug(f"Cleaning up orphaned CrontabSchedule: {crontab_schedule.id}")
    crontab_schedule.delete()
