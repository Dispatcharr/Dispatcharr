"""
Reusable scheduling utilities for creating/updating/deleting
Celery Beat periodic tasks with interval or cron-based schedules.
"""

import json
import logging

from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

from core.models import CoreSettings

logger = logging.getLogger(__name__)


def parse_cron_expression(cron_expression):
    """
    Parse a 5-part cron expression into its components.

    Args:
        cron_expression: A string like "0 3 * * *"

    Returns:
        dict with keys: minute, hour, day_of_month, month_of_year, day_of_week

    Raises:
        ValueError: If the expression is not valid 5-part cron.
    """
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        raise ValueError(
            "Cron expression must have 5 parts: minute hour day month weekday"
        )
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day_of_month": parts[2],
        "month_of_year": parts[3],
        "day_of_week": parts[4],
    }


def create_or_update_periodic_task(
    task_name,
    celery_task_path,
    kwargs=None,
    interval_hours=0,
    cron_expression="",
    enabled=True,
):
    """
    Create or update a Celery Beat PeriodicTask. Supports both interval
    (hours) and cron-based scheduling.

    When *cron_expression* is provided and non-empty it takes precedence
    over *interval_hours*.  An interval_hours of 0 (with no cron) means
    the task is disabled.

    Args:
        task_name:        Unique PeriodicTask name.
        celery_task_path: Dotted path to the Celery task function.
        kwargs:           dict of keyword arguments passed to the task.
        interval_hours:   Interval in hours (0 = disabled when no cron).
        cron_expression:  5-part cron string (empty = use interval).
        enabled:          Whether the task should be enabled.

    Returns:
        The PeriodicTask instance (created or updated).
    """
    task_kwargs = json.dumps(kwargs or {})

    # Determine effective enabled state
    use_cron = bool(cron_expression and cron_expression.strip())
    should_be_enabled = enabled and (use_cron or interval_hours > 0)

    # Retrieve existing task (if any) to track old schedule objects
    old_interval = None
    old_crontab = None
    try:
        existing = PeriodicTask.objects.get(name=task_name)
        old_interval = existing.interval
        old_crontab = existing.crontab
    except PeriodicTask.DoesNotExist:
        existing = None

    if use_cron:
        # ---- Cron-based schedule ----
        cron_parts = parse_cron_expression(cron_expression)
        system_tz = CoreSettings.get_system_time_zone()

        crontab, _ = CrontabSchedule.objects.get_or_create(
            minute=cron_parts["minute"],
            hour=cron_parts["hour"],
            day_of_week=cron_parts["day_of_week"],
            day_of_month=cron_parts["day_of_month"],
            month_of_year=cron_parts["month_of_year"],
            timezone=system_tz,
        )

        defaults = {
            "task": celery_task_path,
            "crontab": crontab,
            "interval": None,
            "enabled": should_be_enabled,
            "kwargs": task_kwargs,
        }

        task, created = PeriodicTask.objects.update_or_create(
            name=task_name, defaults=defaults
        )

        # Clean up old interval if we switched from interval → cron
        if old_interval:
            _cleanup_orphaned_interval(old_interval)
        # Clean up old crontab if it changed
        if old_crontab and old_crontab.id != crontab.id:
            _cleanup_orphaned_crontab(old_crontab)

    else:
        # ---- Interval-based schedule ----
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=max(int(interval_hours), 1) if interval_hours else 1,
            period=IntervalSchedule.HOURS,
        )

        defaults = {
            "task": celery_task_path,
            "interval": interval,
            "crontab": None,
            "enabled": should_be_enabled,
            "kwargs": task_kwargs,
        }

        task, created = PeriodicTask.objects.update_or_create(
            name=task_name, defaults=defaults
        )

        # Clean up old crontab if we switched from cron → interval
        if old_crontab:
            _cleanup_orphaned_crontab(old_crontab)
        # Clean up old interval if it changed
        if old_interval and old_interval.id != interval.id:
            _cleanup_orphaned_interval(old_interval)

    action = "Created" if created else "Updated"
    mode = "cron" if use_cron else "interval"
    logger.info(f"{action} periodic task '{task_name}' ({mode}, enabled={should_be_enabled})")
    return task


def delete_periodic_task(task_name):
    """
    Delete a PeriodicTask by name and clean up orphaned schedules.

    Args:
        task_name: The unique name of the PeriodicTask.

    Returns:
        True if a task was found and deleted, False otherwise.
    """
    try:
        task = PeriodicTask.objects.get(name=task_name)
    except PeriodicTask.DoesNotExist:
        logger.warning(f"No PeriodicTask found with name '{task_name}'")
        return False

    old_interval = task.interval
    old_crontab = task.crontab
    task_id = task.id

    task.delete()
    logger.info(f"Deleted periodic task '{task_name}' (id={task_id})")

    if old_interval:
        _cleanup_orphaned_interval(old_interval)
    if old_crontab:
        _cleanup_orphaned_crontab(old_crontab)

    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cleanup_orphaned_interval(interval_schedule):
    """Delete an IntervalSchedule if no PeriodicTasks reference it."""
    if interval_schedule is None:
        return
    if PeriodicTask.objects.filter(interval=interval_schedule).exists():
        return
    logger.debug(f"Cleaning up orphaned IntervalSchedule {interval_schedule.id}")
    interval_schedule.delete()


def _cleanup_orphaned_crontab(crontab_schedule):
    """Delete a CrontabSchedule if no PeriodicTasks reference it."""
    if crontab_schedule is None:
        return
    if PeriodicTask.objects.filter(crontab=crontab_schedule).exists():
        return
    logger.debug(f"Cleaning up orphaned CrontabSchedule {crontab_schedule.id}")
    crontab_schedule.delete()
