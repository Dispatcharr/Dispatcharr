"""Attribute startup output that runs before logging is configured."""

import logging
import sys
import time
from datetime import datetime, timezone


def startup_log(message):
    """Print in the collector's canonical grammar so the line carries a real source."""
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S") + f",{now.microsecond // 1000:03d}"
    print(f"{stamp} INFO dispatcharr.startup {message}", flush=True)


def canonical_formatter():
    """Formatter matching the collector grammar, stamped in UTC."""
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    formatter.converter = time.gmtime
    return formatter


def configure_early_logging(level):
    """Give pre-dictConfig logger output the canonical shape instead of the bare last-resort form."""
    if isinstance(level, str):
        level = logging.getLevelNamesMapping().get(level, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(canonical_formatter())
    # basicConfig only installs on a bare root, so a second caller just tightens the level.
    logging.basicConfig(handlers=[handler])
    logging.getLogger().setLevel(level)
    logging.captureWarnings(True)
