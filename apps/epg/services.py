"""Commit-linked EPG revisions and bounded programme metadata updates."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from itertools import islice

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import EPGRevision, ProgramData

MISSING = object()
MAX_PROGRAMME_UPDATES = 500
_METADATA_FIELDS = {"title", "sub_title", "description", "custom_properties"}
_EXPECTED_FIELDS = _METADATA_FIELDS | {
    "epg_id", "start_time", "end_time", "tvg_id", "program_id",
}


@dataclass(frozen=True)
class ProgrammeUpdate:
    """Compare expected fields and merge values into one existing programme.

    Property dictionaries compare/merge top-level keys. MISSING distinguishes
    absent expected keys from JSON null, and deletes keys when used in values.
    """

    programme_id: int
    expected: dict
    values: dict


@dataclass(frozen=True)
class ProgrammeUpdateResult:
    """Programme IDs classified by outcome; changed means would-change in preview."""

    changed: tuple[int, ...]
    unchanged: tuple[int, ...]
    conflicts: tuple[int, ...]
    missing: tuple[int, ...]


def get_epg_revision() -> str:
    """Read the committed cache namespace (or initialize it after a DB reset)."""
    revision, _ = EPGRevision.objects.get_or_create(pk=1)
    return str(revision.revision)


@transaction.atomic
def advance_epg_revision() -> str:
    """Advance within the caller's transaction, without depending on Redis.

    Call once after a changed EPG batch. An enclosing rollback also rolls back
    this revision; a recreated row gets a new UUID rather than reusing old keys.
    """
    revision, _ = EPGRevision.objects.select_for_update().get_or_create(pk=1)
    revision.revision = uuid.uuid4()
    revision.save(update_fields=["revision"])
    return str(revision.revision)


def _json_value(value):
    """Validate JSON without silently coercing tuples, object keys or NaN."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValidationError("Properties must contain finite, serializable JSON values.") from exc
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValidationError("Property object keys must be strings.")
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValidationError("Properties must contain JSON values.")


def _validate_scalar(name, value, *, expected):
    if name == "epg_id":
        if type(value) is not int or value <= 0:
            raise ValidationError("Expected epg_id must be a positive integer.")
        ProgramData._meta.get_field("epg").target_field.run_validators(value)
        return
    if name in ("start_time", "end_time"):
        if not isinstance(value, datetime) or timezone.is_naive(value):
            raise ValidationError("Expected programme times must be timezone-aware datetimes.")
        return
    field = ProgramData._meta.get_field(name)
    if value is not None and not isinstance(value, str):
        raise ValidationError(f"{name} must be a string or an allowed null.")
    # Comparisons may describe historical empty strings; new values must obey
    # the model's blank/null rules and validators as well as its field type.
    if expected:
        if value is None and not field.null:
            raise ValidationError(f"{name} does not allow null.")
        field.run_validators(value)
    else:
        field.clean(value, None)


def _validate_fields(fields, *, expected):
    allowed = _EXPECTED_FIELDS if expected else _METADATA_FIELDS
    if not isinstance(fields, dict) or fields.keys() - allowed:
        raise ValidationError("Unsupported programme fields or invalid field mapping.")
    for name, value in fields.items():
        if name != "custom_properties":
            _validate_scalar(name, value, expected=expected)
            continue
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            raise ValidationError("custom_properties must map string keys to expected or new values.")
        for item in value.values():
            if item is not MISSING:
                _json_value(item)


def _validate_updates(updates):
    try:
        updates = list(islice(iter(updates), MAX_PROGRAMME_UPDATES + 1))
    except TypeError as exc:
        raise ValidationError("updates must be an iterable of ProgrammeUpdate objects.") from exc
    if len(updates) > MAX_PROGRAMME_UPDATES:
        raise ValidationError(f"A batch may contain at most {MAX_PROGRAMME_UPDATES} programmes.")
    ids = set()
    for update in updates:
        if not isinstance(update, ProgrammeUpdate):
            raise ValidationError("Each update must be a ProgrammeUpdate.")
        if type(update.programme_id) is not int or update.programme_id <= 0 or update.programme_id in ids:
            raise ValidationError("Programme IDs must be distinct positive integers.")
        ProgramData._meta.pk.run_validators(update.programme_id)
        ids.add(update.programme_id)
        _validate_fields(update.expected, expected=True)
        _validate_fields(update.values, expected=False)
        if update.values.keys() - update.expected.keys():
            raise ValidationError("Every updated field requires an expected value.")
        properties = update.values.get("custom_properties", {})
        if properties.keys() - update.expected.get("custom_properties", {}).keys():
            raise ValidationError("Every updated property key requires an expected value.")
    return updates


def _property_equal(actual, expected):
    if actual is MISSING or expected is MISSING:
        return actual is expected
    # Python considers True == 1, including inside dictionaries. JSON compare
    # retains that type distinction and ignores object-key ordering.
    return json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def _matches(programme, expected):
    for name, value in expected.items():
        actual = getattr(programme, name)
        if name == "custom_properties":
            if not isinstance(actual, dict):
                return False
            if any(not _property_equal(actual.get(key, MISSING), item) for key, item in value.items()):
                return False
        elif actual != value:
            return False
    return True


def _changes(programme, values):
    changes = {}
    for name, value in values.items():
        if name == "custom_properties":
            properties = programme.custom_properties.copy()
            for key, item in value.items():
                if item is MISSING:
                    properties.pop(key, None)
                else:
                    properties[key] = item
            if not _property_equal(properties, programme.custom_properties):
                changes[name] = properties
        elif value != getattr(programme, name):
            changes[name] = value
    return changes


def update_programmes(updates, *, preview=False) -> ProgrammeUpdateResult:
    """Apply at most 500 metadata updates using row locks and expected values.

    Validate the whole request before writes. Missing/conflicting programmes
    are skipped; matching changes and one revision advance commit atomically.
    Schedule/source fields are comparison-only. Preview and no-op batches do
    not write. Errors propagate so callers cannot mistake a failed commit for
    successful cache visibility. No Redis operation is required.
    """
    if type(preview) is not bool:
        raise ValidationError("preview must be a boolean.")
    updates = _validate_updates(updates)
    changed, unchanged, conflicts, missing = [], [], [], []
    with transaction.atomic():
        rows = {
            row.pk: row for row in ProgramData.objects.select_for_update()
            .filter(pk__in=[update.programme_id for update in updates]).order_by("pk")
        }
        for update in updates:
            programme = rows.get(update.programme_id)
            if programme is None:
                missing.append(update.programme_id)
            elif not _matches(programme, update.expected):
                conflicts.append(update.programme_id)
            else:
                changes = _changes(programme, update.values)
                if changes:
                    if not preview:
                        ProgramData.objects.filter(pk=programme.pk).update(**changes)
                    changed.append(programme.pk)
                else:
                    unchanged.append(programme.pk)
        if changed and not preview:
            advance_epg_revision()
    return ProgrammeUpdateResult(tuple(changed), tuple(unchanged), tuple(conflicts), tuple(missing))
