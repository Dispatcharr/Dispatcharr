import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

_REFRESH_INTERVAL_SECONDS = 5.0
_cache = {"zone": None, "checked": 0.0}


def _env_zone():
    from django.conf import settings

    try:
        return ZoneInfo(getattr(settings, "DISPATCHARR_DISPLAY_TZ", "UTC"))
    except Exception:
        return ZoneInfo("UTC")


def refresh_display_zone(force=False):
    """Refresh the cached display zone from CoreSettings.

    Only call from contexts that may safely run a database query
    (request/task start, settings writes) — never from the logging path:
    an emit-time query deadlocks on the psycopg connection lock when the
    log record itself originates inside a database call.
    """
    now = time.monotonic()
    if not force and now - _cache["checked"] < _REFRESH_INTERVAL_SECONDS:
        return
    _cache["checked"] = now
    try:
        from core.models import CoreSettings

        _cache["zone"] = ZoneInfo(CoreSettings.get_system_time_zone())
    except Exception:
        # Database or app registry not ready, or an invalid stored zone —
        # keep the previous value (the env capture until a refresh lands).
        pass


class DisplayTimezoneFormatter(logging.Formatter):
    def __init__(self, format=None, datefmt=None, style="%"):
        super().__init__(fmt=format, datefmt=datefmt, style=style)

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=_cache["zone"] or _env_zone())
        if datefmt:
            return dt.strftime(datefmt)
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S')},{int(record.msecs):03d}"
