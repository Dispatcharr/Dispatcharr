import logging
import time


class DisplayTimezoneFormatter(logging.Formatter):
    """Stamps records in UTC; the log collector renders the display zone."""

    converter = time.gmtime

    def __init__(self, format=None, datefmt=None, style="%"):
        super().__init__(fmt=format, datefmt=datefmt, style=style)

    def format(self, record):
        # Indent embedded newlines so the collector keeps a multi-line record
        # (tracebacks, celery's task stubs) attached to its stamped header.
        return super().format(record).replace("\n", "\n ")
