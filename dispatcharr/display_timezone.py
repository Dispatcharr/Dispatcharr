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


def format_display_timestamp(dt, msecs):
    # Non-UTC stamps carry their offset so persisted logs are unambiguous.
    base = f"{dt.strftime('%Y-%m-%d %H:%M:%S')},{msecs:03d}"
    offset = dt.strftime("%z")
    if offset and offset != "+0000":
        return f"{base} {offset}"
    return base


def set_display_zone(zone_name):
    try:
        _cache["zone"] = ZoneInfo(zone_name)
        _cache["checked"] = time.monotonic()
    except Exception:
        pass


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
        return format_display_timestamp(dt, int(record.msecs))
