"""Canonical identity maintenance; source metadata never participates."""

from django.db import transaction


def has_manual_source_assignment(relation):
    return bool(
        relation.tmdb_override_id
        or (relation.custom_properties or {}).get("_library_manual_assignment") is True
    )


def remember_alias(source, target, content_type, requirements=None):
    from .models import VODContentAlias

    VODContentAlias.objects.filter(
        content_type=content_type, target_id=source.pk
    ).update(target_id=target.pk)
    VODContentAlias.objects.update_or_create(
        content_type=content_type,
        legacy_id=source.pk,
        defaults={
            "legacy_uuid": source.uuid,
            "target_id": target.pk,
            "requirements": requirements or {},
        },
    )


def move_series_episodes(source, target):
    from .models import Episode, M3UEpisodeRelation

    for episode in Episode.objects.filter(series=source).order_by("pk"):
        # Unknown episode numbering is not evidence of identical episodes.
        collision = None
        if episode.season_number is not None and episode.episode_number is not None:
            collision = Episode.objects.filter(
                series=target,
                season_number=episode.season_number,
                episode_number=episode.episode_number,
            ).first()
        if collision is None:
            episode.series = target
            episode.save(update_fields=["series"])
        else:
            for field in ("tmdb_id", "imdb_id"):
                if (
                    getattr(episode, field)
                    and getattr(collision, field)
                    and getattr(episode, field) != getattr(collision, field)
                ):
                    raise ValueError(
                        "Conflicting episode identifiers; canonical merge aborted."
                    )
            M3UEpisodeRelation.objects.filter(episode=episode).update(episode=collision)
            remember_alias(episode, collision, "episode")
            episode.delete()


@transaction.atomic
def handle_identity_conflicts(current, relation, tmdb_id, imdb_id):
    """Keep the selected row and preserve retired IDs when details reveal identity."""
    from .models import M3UMovieRelation, M3USeriesRelation, Movie

    model = type(current)
    kind = "movie" if isinstance(current, Movie) else "series"
    relation_model = M3UMovieRelation if kind == "movie" else M3USeriesRelation
    matches = model.objects.none()
    from django.db.models import Q

    query = Q()
    if tmdb_id:
        query |= Q(tmdb_id=str(tmdb_id))
    if imdb_id:
        query |= Q(imdb_id=str(imdb_id))
    if tmdb_id or imdb_id:
        matches = model.objects.filter(query)
    ids = set(matches.values_list("pk", flat=True)) | {current.pk}
    rows = list(model.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    for field, incoming in (("tmdb_id", tmdb_id), ("imdb_id", imdb_id)):
        values = {str(getattr(row, field)) for row in rows if getattr(row, field)}
        if incoming:
            values.add(str(incoming))
        if len(values) > 1:
            raise ValueError(
                "Conflicting external identifiers; canonical merge aborted."
            )
    from .library import merge_library_state

    merge_library_state(current, rows)
    for donor in rows:
        if donor.pk == current.pk:
            continue
        for field in (
            "description",
            "year",
            "rating",
            "genre",
            "logo_id",
            "tmdb_id",
            "imdb_id",
        ):
            if current.tmdb_lookup_excluded and field not in {"tmdb_id", "imdb_id"}:
                continue
            if not getattr(current, field) and getattr(donor, field):
                setattr(current, field, getattr(donor, field))
        if not current.tmdb_lookup_excluded:
            current.custom_properties = {
                **(donor.custom_properties or {}),
                **(current.custom_properties or {}),
            }
        if kind == "movie":
            current.is_adult = current.is_adult or donor.is_adult
        relation_model.objects.filter(**{kind: donor}).update(**{kind: current})
        if kind == "series":
            move_series_episodes(donor, current)
        remember_alias(donor, current, kind)
        donor.delete()
    if tmdb_id:
        current.tmdb_id = str(tmdb_id)
    if imdb_id:
        current.imdb_id = str(imdb_id)
    current.save()
    return current, False
