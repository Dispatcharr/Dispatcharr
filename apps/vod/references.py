"""Stable output IDs for a canonical title plus explicit source requirements.

Use the content table's existing sequence to reserve public IDs. A selection
can therefore never collide with an old or future Movie/Series/Episode ID.
This contract is independent of the later profile editor/catalogue builder.
"""

import hashlib
import json
import uuid
from types import SimpleNamespace

from django.db import connection, transaction
from django.db.models import Max
from .metadata import validate_source_metadata


def selection_key(content_type, target_id, requirements):
    normalized = {
        key: sorted(value) if isinstance(value, list) else value
        for key, value in requirements.items()
    }
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    return f"{content_type}:{target_id}:{digest}"


def _reserve_ids(model, count, content_type):
    from .models import VODContentAlias

    table = model._meta.db_table
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute(
                "SELECT nextval(pg_get_serial_sequence(%s, 'id')) FROM generate_series(1, %s)",
                [table, count],
            )
            return [row[0] for row in cursor.fetchall()]
        # SQLite is only the explicitly supported isolated-test fallback.
        if connection.vendor != "sqlite":
            raise RuntimeError("Unsupported VOD public-ID allocator.")
        cursor.execute("SELECT seq FROM sqlite_sequence WHERE name = %s", [table])
        row = cursor.fetchone()
        sequence = row[0] if row else 0
        maximum = max(
            sequence,
            model.objects.aggregate(value=Max("id"))["value"] or 0,
            VODContentAlias.objects.filter(content_type=content_type).aggregate(
                value=Max("legacy_id")
            )["value"]
            or 0,
        )
        if row:
            cursor.execute(
                "UPDATE sqlite_sequence SET seq = %s WHERE name = %s",
                [maximum + count, table],
            )
        else:
            cursor.execute(
                "INSERT INTO sqlite_sequence(name, seq) VALUES (%s, %s)",
                [table, maximum + count],
            )
        return list(range(maximum + 1, maximum + count + 1))


def output_references(content_type, selections):
    """Resolve a catalogue batch in bounded queries, creating only missing IDs."""
    from .models import Episode, Movie, Series

    model = {"movie": Movie, "series": Series, "episode": Episode}[content_type]
    selections = [
        (target_id, validate_source_metadata(requirements))
        for target_id, requirements in selections
    ]
    wanted = {
        selection_key(content_type, target_id, requirements): (target_id, requirements)
        for target_id, requirements in selections
    }
    # An unconstrained canonical selection is the historical public ID; it
    # needs no extra row and preserves existing integrations unchanged.
    direct = {
        key: SimpleNamespace(legacy_id=target_id, requirements={})
        for key, (target_id, requirements) in wanted.items()
        if not requirements
    }
    wanted = {key: value for key, value in wanted.items() if key not in direct}
    if not wanted:
        return direct
    return {**direct, **_aliases(content_type, model, wanted)}


def source_references(content_type, sources):
    """Stable output IDs for single provider sources of a title, by source ID.

    The profile catalogue pins each of these IDs to its one source, so they
    carry no requirements of their own.
    """
    from .models import Episode, Movie, Series

    model = {"movie": Movie, "series": Series, "episode": Episode}[content_type]
    keys = {
        relation_id: f"{content_type}:{target_id}:source:{relation_id}"
        for target_id, relation_id in sources
    }
    found = _aliases(
        content_type,
        model,
        {keys[relation_id]: (target_id, {}) for target_id, relation_id in sources},
    )
    return {relation_id: found[key] for relation_id, key in keys.items()}


def _aliases(content_type, model, wanted):
    """Existing aliases for the wanted selection keys, creating missing ones."""
    from .models import VODContentAlias

    def existing():
        result = {}
        keys = list(wanted)
        for offset in range(0, len(keys), 1000):
            result.update(
                {
                    row.selection_key: row
                    for row in VODContentAlias.objects.filter(
                        selection_key__in=keys[offset : offset + 1000]
                    )
                }
            )
        return result

    found = existing()
    if len(found) == len(wanted):
        return found
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                # Serialise first publication only; established selections are
                # read without this lock and never consume sequence values.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    [f"vod-public-ids:{content_type}"],
                )
        found = existing()
        missing = [key for key in wanted if key not in found]
        public_ids = _reserve_ids(model, len(missing), content_type) if missing else []
        rows = [
            VODContentAlias(
                content_type=content_type,
                selection_key=key,
                legacy_id=public_id,
                legacy_uuid=uuid.uuid4(),
                target_id=wanted[key][0],
                requirements=wanted[key][1],
            )
            for key, public_id in zip(missing, public_ids)
        ]
        VODContentAlias.objects.bulk_create(rows, batch_size=500)
        found.update({row.selection_key: row for row in rows})
    return found


def output_reference(content_type, target_id, requirements):
    requirements = validate_source_metadata(requirements)
    key = selection_key(content_type, target_id, requirements)
    return output_references(content_type, [(target_id, requirements)])[key]
