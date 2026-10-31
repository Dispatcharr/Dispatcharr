"""Small source-selection contract reused by output, details and playback.

Profiles can supply requirements later without changing content identity or
introducing another language grouping in the database.
"""

import uuid

from .metadata import (
    category_key,
    category_metadata_map,
    effective_source_metadata,
    metadata_satisfies,
    requirements_from_metadata,
)


def resolve_content(content_type, identifier, *, by_uuid=False):
    from .models import Episode, Movie, Series, VODContentAlias

    model = {"movie": Movie, "series": Series, "episode": Episode}.get(content_type)
    if model is None:
        return None, {}
    try:
        value = uuid.UUID(str(identifier)) if by_uuid else int(identifier)
    except (ValueError, TypeError, AttributeError):
        return None, {}
    if not by_uuid and value < 1:
        return None, {}
    obj = model.objects.filter(**{"uuid" if by_uuid else "pk": value}).first()
    if obj is not None:
        return obj, {}
    alias = VODContentAlias.objects.filter(
        content_type=content_type,
        **{"legacy_uuid" if by_uuid else "legacy_id": value},
    ).first()
    if alias is None:
        return None, {}
    return model.objects.filter(pk=alias.target_id).first(), alias.requirements or {}


def content_is_blocked(content):
    """A canonical output block applies to every source and every series episode.

    Metadata protection is unrelated. Management can still inspect and edit a
    blocked title, but client catalogs, details and playback must fail closed.
    """
    from .models import Episode, Movie, Series

    if isinstance(content, (Movie, Series)):
        return content.library_blocked
    return isinstance(content, Episode) and content.series.library_blocked


def available_source_relations(relations):
    """Global blocks are mandatory before any present or future profile rules."""
    from django.db.models import QuerySet

    from .models import M3UEpisodeRelation, M3UMovieRelation, M3USeriesRelation

    paths = {
        M3UMovieRelation: "movie__library_blocked",
        M3USeriesRelation: "series__library_blocked",
        M3UEpisodeRelation: "episode__series__library_blocked",
    }
    if isinstance(relations, QuerySet) and relations.model in paths:
        return list(relations.filter(**{paths[relations.model]: False}))
    rows = list(relations)
    blocked = set()
    for model, path in paths.items():
        ids = [row.pk for row in rows if isinstance(row, model)]
        if ids:
            blocked.update(
                (model, pk)
                for pk in model.objects.filter(pk__in=ids, **{path: True}).values_list(
                    "pk", flat=True
                )
            )
    return [row for row in rows if (type(row), getattr(row, "pk", None)) not in blocked]


def source_candidates(
    relations, *, requirements=None, preferred_relation=None, preserve_selection=True
):
    """Filter first, then retain the established account-priority ordering.

    Explicit requirements fail closed on unknown metadata. Once a source has
    been selected, capacity fallback cannot silently lose its known languages,
    resolution or video features. This is not mid-stream/file-level failover.
    """
    relations = available_source_relations(relations)
    mapping = category_metadata_map(relations)
    metadata = {
        relation.id: effective_source_metadata(
            relation, category_defaults=mapping.get(category_key(relation), {})
        )["values"]
        for relation in relations
    }
    required = requirements or {}
    eligible = [
        relation
        for relation in relations
        if metadata_satisfies(metadata[relation.id], required)
    ]
    if preferred_relation is not None:
        eligible.sort(key=lambda relation: relation.id != preferred_relation.id)
    if preserve_selection and eligible:
        anchor = eligible[0]
        selected_requirements = {
            **requirements_from_metadata(metadata[anchor.id]),
            **required,
        }
        eligible = [
            relation
            for relation in eligible
            if metadata_satisfies(metadata[relation.id], selected_requirements)
        ]
    return eligible


def select_source(relations, *, requirements=None):
    eligible = source_candidates(relations, requirements=requirements)
    return eligible[0] if eligible else None
