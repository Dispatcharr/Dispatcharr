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


class _CanonicalFormatter(logging.Formatter):
    converter = time.gmtime

    def format(self, record):
        # Indent embedded newlines so the collector keeps a multi-line record attached to its stamped header.
        return super().format(record).replace("\n", "\n ")


def canonical_formatter():
    """Formatter matching the collector grammar, stamped in UTC."""
    return _CanonicalFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")


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
