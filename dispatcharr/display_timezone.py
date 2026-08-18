import logging
import time


class DisplayTimezoneFormatter(logging.Formatter):
    """Stamps records in UTC; the log collector renders the display zone."""

    converter = time.gmtime

    def __init__(self, format=None, datefmt=None, style="%"):
        super().__init__(fmt=format, datefmt=datefmt, style=style)
