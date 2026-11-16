"""Model fields that mask provider credentials before they are stored.

Provider errors often quote the request URL, and XC URLs carry the login
(``/live/user/pass/``, ``?username=..&password=..``). Status messages and
system event details are written from dozens of places, many through
``QuerySet.update()``, so the masking lives on the field: every write goes
through ``get_prep_value``. It uses the same rules as the log collector
(``dispatcharr.log_redaction``).
"""

from django.db import models

from dispatcharr.log_redaction import redact_text


def redact_value(value):
    """Mask credentials in strings, recursing into dicts and lists."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    return value


class RedactedTextField(models.TextField):
    def get_prep_value(self, value):
        return redact_value(super().get_prep_value(value))


class RedactedJSONField(models.JSONField):
    def get_prep_value(self, value):
        return super().get_prep_value(redact_value(value))
