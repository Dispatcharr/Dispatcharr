"""Replace language identity atomically; never reuse a retired public ID.

Merging is intentionally irreversible. Restore a database backup to roll back
this migration. It must run with catalogue writers stopped.
"""

import uuid
from collections import defaultdict

from django.db import migrations, models


def migrate_catalog(apps, schema_editor):
    # This vendored standard table is data, not mutable application logic.
    from apps.vod.language_codes import LANGUAGES

    aliases = {
        alias: code
        for code, entry in LANGUAGES.items()
        for alias in (code, entry.get("alpha2"), entry.get("terminological"))
        if alias
    }
    db = schema_editor.connection.alias
    Movie = apps.get_model("vod", "Movie")
    Series = apps.get_model("vod", "Series")
    Episode = apps.get_model("vod", "Episode")
    Alias = apps.get_model("vod", "VODContentAlias")
    MovieSource = apps.get_model("vod", "M3UMovieRelation")
    SeriesSource = apps.get_model("vod", "M3USeriesRelation")
    EpisodeSource = apps.get_model("vod", "M3UEpisodeRelation")
    Category = apps.get_model("vod", "M3UVODCategoryRelation")

    def metadata(properties):
        properties = properties if isinstance(properties, dict) else {}
        result = {}
        for field in ("audio_languages", "subtitle_languages"):
            raw = properties.get(field)
            if isinstance(raw, list) and all(
                isinstance(code, str) and code.lower() in aliases for code in raw
            ):
                result[field] = list(
                    dict.fromkeys(aliases[code.lower()] for code in raw)
                )
        if "audio_languages" not in result:
            language = aliases.get(str(properties.get("language") or "").lower())
            if language:
                result["audio_languages"] = [language]
        quality = properties.get("resolution") or properties.get("quality")
        if not isinstance(quality, str):
            quality = None
        quality = {"4K": "2160p", "8K": "4320p"}.get(quality, quality)
        if quality in (
            "4320p",
            "2160p",
            "1440p",
            "1080p",
            "720p",
            "576p",
            "480p",
            "SD",
        ):
            result["resolution"] = quality
        features = properties.get("video_features")
        if isinstance(features, list) and all(
            feature in ("3d", "hdr", "dv") for feature in features
        ):
            result["video_features"] = list(dict.fromkeys(features))
        return result

    def language_requirement(language):
        if not language:
            return {}
        code = aliases.get(language.lower())
        return {"audio_languages": [code]} if code else {"unresolved_language": True}

    def groups_for(model):
        rows = list(model.objects.using(db).all().order_by("pk"))
        changed = []
        for row in rows:
            dirty = False
            for field in ("tmdb_id", "imdb_id"):
                original = getattr(row, field)
                clean = str(original).strip() if original is not None else None
                clean = None if clean in ("", "0") else clean
                if original != clean:
                    setattr(row, field, clean)
                    dirty = True
            if dirty:
                changed.append(row)
        if changed:
            model.objects.using(db).bulk_update(
                changed, ["tmdb_id", "imdb_id"], batch_size=500
            )
        parent = {row.pk: row.pk for row in rows}

        def root(key):
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key

        identities = {}
        for row in rows:
            keys = []
            for field in ("tmdb_id", "imdb_id"):
                if getattr(row, field):
                    keys.append((field, str(getattr(row, field))))
            if not keys and row.year is not None:
                keys.append(("name_year", row.name, row.year))
            for key in keys:
                if key in identities:
                    parent[root(row.pk)] = root(identities[key])
                else:
                    identities[key] = row.pk
        grouped = defaultdict(list)
        for row in rows:
            grouped[root(row.pk)].append(row)
        result = list(grouped.values())
        # Preflight all groups before changing any content. Contradictory IDs
        # are not evidence of a shared title, even when one ID overlaps.
        for group in result:
            for field in ("tmdb_id", "imdb_id"):
                if (
                    len(
                        {
                            str(getattr(row, field))
                            for row in group
                            if getattr(row, field)
                        }
                    )
                    > 1
                ):
                    raise RuntimeError(
                        "Conflicting VOD external identifiers; migration aborted without merging."
                    )
        return result

    movie_groups, series_groups = groups_for(Movie), groups_for(Series)
    if schema_editor.connection.vendor == "postgresql":
        # Never reset a sequence down to MAX(id): deleted/catalogue IDs may
        # still be cached by clients. Only advance sequences if explicit IDs
        # from an old import/restore left them behind the table maximum.
        for model in (Movie, Series, Episode):
            maximum = (
                model.objects.using(db).aggregate(value=models.Max("pk"))["value"] or 0
            )
            with schema_editor.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT nextval(pg_get_serial_sequence(%s, 'id'))",
                    [model._meta.db_table],
                )
                current = cursor.fetchone()[0]
                if maximum > current:
                    cursor.execute(
                        "SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, true)",
                        [model._meta.db_table, maximum],
                    )

    for row in Category.objects.using(db).all().iterator(chunk_size=500):
        row.metadata_defaults = metadata(row.custom_properties)
        properties = dict(row.custom_properties or {})
        metadata_keys = {
            "language",
            "quality",
            "audio_languages",
            "subtitle_languages",
            "resolution",
            "video_features",
        }
        original = {
            key: properties.pop(key) for key in list(properties) if key in metadata_keys
        }
        if original:
            properties["legacy_metadata"] = {
                **properties.get("legacy_metadata", {}),
                **original,
            }
        row.custom_properties = properties
        row.save(using=db, update_fields=["metadata_defaults", "custom_properties"])

    # Provider declarations remain separate from category-assigned defaults.
    # Scalar legacy category language is not claimed as a measured audio track.
    for source_model in (MovieSource, SeriesSource, EpisodeSource):
        pending = []
        for source in source_model.objects.using(db).all().iterator(chunk_size=500):
            declared = {}
            for payload in ("info", "basic_data", "detailed_info"):
                raw = (source.custom_properties or {}).get(payload) or {}
                explicit = (
                    {
                        key: raw[key]
                        for key in (
                            "audio_languages",
                            "subtitle_languages",
                            "resolution",
                            "video_features",
                            "quality",
                        )
                        if key in raw
                    }
                    if isinstance(raw, dict)
                    else {}
                )
                declared.update(metadata(explicit))
            source.declared_metadata = declared
            pending.append(source)
            if len(pending) == 500:
                source_model.objects.using(db).bulk_update(
                    pending, ["declared_metadata"]
                )
                pending.clear()
        if pending:
            source_model.objects.using(db).bulk_update(pending, ["declared_metadata"])

    def clone(model, rows, **overrides):
        values = {}
        for field in model._meta.concrete_fields:
            if field.primary_key or field.name in {
                "uuid",
                "language",
                "created_at",
                "updated_at",
            }:
                continue
            candidates = [getattr(row, field.attname) for row in rows]
            if field.name == "is_adult":
                values[field.attname] = any(candidates)
            elif field.name == "custom_properties":
                merged = {}
                for payload in candidates:
                    for key, value in (payload or {}).items():
                        if merged.get(key) in (None, "", {}, []) and value not in (
                            None,
                            "",
                            {},
                            [],
                        ):
                            merged[key] = value
                values[field.attname] = merged or None
            else:
                values[field.attname] = next(
                    (value for value in candidates if value not in (None, "", {}, [])),
                    candidates[0],
                )
        values.update(uuid=uuid.uuid4(), **overrides)
        if model in (Movie, Series):
            values["language"] = ""
        target = model.objects.using(db).create(**values)
        model.objects.using(db).filter(pk=target.pk).update(
            created_at=min(row.created_at for row in rows),
        )
        return target

    def remember(row, target, kind, requirements):
        Alias.objects.using(db).create(
            content_type=kind,
            legacy_id=row.pk,
            legacy_uuid=row.uuid,
            target_id=target.pk,
            requirements=requirements,
        )

    def merge_group(model, sources, kind, group):
        if len(group) == 1 and not group[0].language:
            return
        target = clone(model, group)
        if kind == "series":
            by_episode = defaultdict(list)
            for series in group:
                for episode in (
                    Episode.objects.using(db).filter(series_id=series.pk).order_by("pk")
                ):
                    key = (episode.season_number, episode.episode_number)
                    if None in key:
                        key = ("unknown", episode.pk)
                    by_episode[key].append((episode, series.language))
            for entries in by_episode.values():
                episodes = [entry[0] for entry in entries]
                for field in ("tmdb_id", "imdb_id"):
                    if (
                        len(
                            {
                                str(getattr(row, field))
                                for row in episodes
                                if getattr(row, field)
                            }
                        )
                        > 1
                    ):
                        raise RuntimeError(
                            "Conflicting VOD episode identifiers; migration aborted without merging."
                        )
                merged = clone(Episode, episodes, series_id=target.pk)
                for episode, language in entries:
                    EpisodeSource.objects.using(db).filter(
                        episode_id=episode.pk
                    ).update(episode_id=merged.pk)
                    remember(episode, merged, "episode", language_requirement(language))
                    episode.delete(using=db)
        for row in group:
            sources.objects.using(db).filter(**{f"{kind}_id": row.pk}).update(
                **{f"{kind}_id": target.pk}
            )
            remember(row, target, kind, language_requirement(row.language))
            row.delete(using=db)

    for group in movie_groups:
        merge_group(Movie, MovieSource, "movie", group)
    for group in series_groups:
        merge_group(Series, SeriesSource, "series", group)
    if schema_editor.connection.vendor == "postgresql":
        # Moving relations schedules deferred FK checks. Flush them before
        # ALTER TABLE removes language, while keeping the whole upgrade atomic.
        schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("vod", "0006_movie_series_language")]

    operations = (
        [
            migrations.AddField(
                model_name=model,
                name=field,
                field=models.JSONField(default=default, blank=True),
            )
            for model in ("m3umovierelation", "m3useriesrelation", "m3uepisoderelation")
            for field, default in (
                ("declared_metadata", dict),
                ("observed_metadata", dict),
                ("manual_metadata", dict),
                ("locked_fields", list),
            )
        ]
        + [
            migrations.AddField(
                model_name=model,
                name="last_observed_at",
                field=models.DateTimeField(null=True, blank=True),
            )
            for model in ("m3umovierelation", "m3useriesrelation", "m3uepisoderelation")
        ]
        + [
            migrations.AddField(
                model_name="m3uvodcategoryrelation",
                name="metadata_defaults",
                field=models.JSONField(default=dict, blank=True),
            ),
            migrations.CreateModel(
                name="VODContentAlias",
                fields=[
                    (
                        "id",
                        models.BigAutoField(
                            auto_created=True,
                            primary_key=True,
                            serialize=False,
                            verbose_name="ID",
                        ),
                    ),
                    (
                        "content_type",
                        models.CharField(
                            max_length=7,
                            choices=[
                                ("movie", "Movie"),
                                ("series", "Series"),
                                ("episode", "Episode"),
                            ],
                        ),
                    ),
                    ("legacy_id", models.PositiveBigIntegerField()),
                    ("legacy_uuid", models.UUIDField()),
                    ("target_id", models.PositiveBigIntegerField()),
                    ("requirements", models.JSONField(default=dict, blank=True)),
                    (
                        "selection_key",
                        models.CharField(
                            max_length=100, unique=True, null=True, blank=True
                        ),
                    ),
                ],
                options={
                    "indexes": [
                        models.Index(
                            fields=["content_type", "target_id"],
                            name="vod_alias_target_idx",
                        )
                    ],
                    "constraints": [
                        models.UniqueConstraint(
                            fields=("content_type", "legacy_id"),
                            name="vod_alias_legacy_id",
                        ),
                        models.UniqueConstraint(
                            fields=("content_type", "legacy_uuid"),
                            name="vod_alias_legacy_uuid",
                        ),
                    ],
                },
            ),
        ]
        + [
            migrations.RemoveConstraint(
                model_name=model, name=f"unique_{model}_{suffix}"
            )
            for model in ("movie", "series")
            for suffix in (
                "tmdb_id_language",
                "imdb_id_language",
                "name_year_language_no_external_id",
            )
        ]
        + [
            migrations.RunPython(migrate_catalog),
        ]
        + [
            migrations.RemoveField(model_name=model, name="language")
            for model in ("movie", "series")
        ]
        + [
            migrations.AddConstraint(
                model_name=model,
                constraint=models.UniqueConstraint(
                    fields=[field],
                    condition=models.Q(**{f"{field}__isnull": False}),
                    name=f"unique_{model}_{field}",
                ),
            )
            for model in ("movie", "series")
            for field in ("tmdb_id", "imdb_id")
        ]
        + [
            migrations.AddConstraint(
                model_name=model,
                constraint=models.UniqueConstraint(
                    fields=["name", "year"],
                    condition=models.Q(tmdb_id__isnull=True)
                    & models.Q(imdb_id__isnull=True),
                    name=f"unique_{model}_name_year_no_external_id",
                ),
            )
            for model in ("movie", "series")
        ]
    )
