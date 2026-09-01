"""Attribute startup output that runs before logging is configured."""

import logging
import os
import sys
import time
from datetime import datetime, timezone

from dispatcharr.display_timezone import DisplayTimezoneFormatter as _StandaloneFormatter
from dispatcharr.log_collector import collector_running


def startup_log(message, level="INFO", source="dispatcharr.startup", stream=None):
    """Print in the collector's canonical grammar so the line carries a real source."""
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S") + f",{now.microsecond // 1000:03d}"
    print(f"{stamp} {level} {source} {message}", flush=True, file=stream or sys.stdout)


class DisplayTimezoneFormatter(_StandaloneFormatter):
    """Stamps records in UTC when a collector renders the display zone;
    a process nothing fronts stamps the display zone itself."""

    converter = time.gmtime

    def __init__(self, format="%(asctime)s %(levelname)s %(name)s %(message)s", datefmt=None, style="%"):
        super().__init__(format=format, datefmt=datefmt, style=style)
        self._fronted = collector_running(
            os.environ.get("DISPATCHARR_LOG_DIR", "/data/logs")
        )

    def formatTime(self, record, datefmt=None):
        if self._fronted:
            return logging.Formatter.formatTime(self, record, datefmt)
        return super().formatTime(record, datefmt)

    def format(self, record):
        line = logging.Formatter.format(self, record)
        if self._fronted:
            # Indent embedded newlines: the collector reads leading whitespace as a continuation.
            return line.replace("\n", "\n ")
        return line


def configure_early_logging(level):
    """Give pre-dictConfig logger output the canonical shape instead of the bare last-resort form."""
    if isinstance(level, str):
        level = logging.getLevelNamesMapping().get(level, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(DisplayTimezoneFormatter())
    # basicConfig only installs on a bare root, so a second caller just tightens the level.
    logging.basicConfig(handlers=[handler])
    logging.getLogger().setLevel(level)
    logging.captureWarnings(True)
