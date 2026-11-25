"""Exclude automatic source refreshes without changing saved Beat schedules."""
from django_celery_beat.schedulers import DatabaseScheduler
from dispatcharr.safe_mode import AUTOMATIC_REFRESH_TASKS


class SafeModeScheduler(DatabaseScheduler):
    def all_as_schedule(self):
        schedule = super().all_as_schedule()
        return {name: entry for name, entry in schedule.items()
                if entry.task not in AUTOMATIC_REFRESH_TASKS}
