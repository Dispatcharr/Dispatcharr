"""Prepared VOD profile catalogues for Xtream Codes output.

A build decides, per profile, which source represents each title (or each
edition or variant), reserves its stable public ID and stores the ordered
fallback sources. Requests then read one generation instead of ranking every
source again. Titles, artwork and blocks stay live at output time.
"""

import hashlib
import json
import re
import uuid
from types import SimpleNamespace

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from .metadata import (
    effective_source_metadata,
    legacy_category_metadata,
    metadata_satisfies,
    requirements_from_metadata,
)
from .models import (
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODContentAlias,
    VODProfile,
    VODProfileEntry,
)
from .references import output_references, selection_key, source_references

BATCH_SIZE = 2000
QUEUE_KEY = "vod-profile-catalogs-queued"
CONTENT = {"movie": (Movie, M3UMovieRelation), "series": (Series, M3USeriesRelation)}
SIGNATURE_FIELDS = (
    "output_mode",
    "category_choices",
    "content_filters",
    "excluded_titles",
    "edition_rules",
    "ranking",
    "audio_language_order",
    "subtitle_language_order",
    "provider_order",
)


def catalog_signature(profile):
    """Fingerprint of every setting that changes which sources a profile offers."""
    config = {field: getattr(profile, field) for field in SIGNATURE_FIELDS}
    config["category_rules"] = (
        list(
            profile.category_rules.values_list(
                "scope", "regex_pattern", "action", "case_sensitive", "enabled", "order"
            )
        )
        if profile.pk
        else []
    )
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def request_catalog_build(profile_ids=None, countdown=30):
    """Debounce rebuilds: one queued run covers every request until it starts."""
    from .tasks import build_vod_profile_catalogs

    key = QUEUE_KEY
    if profile_ids is not None:
        key = f"{QUEUE_KEY}:{','.join(str(pk) for pk in sorted(profile_ids))}"
    if cache.add(key, True, timeout=countdown + 600):
        transaction.on_commit(
            lambda: build_vod_profile_catalogs.apply_async(
                args=[profile_ids, key], countdown=countdown
            )
        )


def refresh_catalog(profile, *, force=False):
    """Queue a rebuild when saved settings change what an active profile offers."""
    if not profile.is_active or (
        not force and catalog_signature(profile) == profile.catalog_signature
    ):
        return
    # A running build notices the change itself and stays pending.
    if profile.catalog_status != VODProfile.CatalogStatus.BUILDING:
        profile.catalog_status = VODProfile.CatalogStatus.PENDING
        profile.save(update_fields=["catalog_status"])
    request_catalog_build([profile.pk], countdown=5)


def output_generation(profile):
    """The generation clients see; None keeps live output for an unbuilt default."""
    if profile.catalog_status == VODProfile.CatalogStatus.PENDING:
        request_catalog_build([profile.pk], countdown=5)
    if profile.catalog_generation:
        return profile.catalog_generation
    return None if profile.is_default else ""


def catalog_entries(profile, generation, content_type):
    return VODProfileEntry.objects.filter(
        profile=profile, generation=generation, content_type=content_type
    )


def profile_source_order(
    user, content_type, content, identifier=None, *, by_uuid=False
):
    """Ordered source IDs a user's profile offers for a title.

    None means unrestricted (live default output); an empty list means the
    profile does not offer the title. Episodes follow their series sources.
    """
    from .profiles import profile_for_user

    profile = profile_for_user(user)
    generation = output_generation(profile)
    if generation is None:
        return None
    kind = "series" if content_type in ("series", "episode") else "movie"
    target = content.series_id if content_type == "episode" else content.pk
    entries = list(
        catalog_entries(profile, generation, kind)
        .filter(content_id=target)
        .values_list("public_id", "source_ids")
    )
    public_id = (
        None
        if content_type == "episode"
        else _public_id(content_type, content, identifier, by_uuid)
    )
    chosen = [ids for pk, ids in entries if pk == public_id] or [
        ids for _pk, ids in entries
    ]
    return list(dict.fromkeys(source for ids in chosen for source in ids))


def _public_id(content_type, content, identifier, by_uuid):
    if identifier is None:
        return None
    if not by_uuid:
        try:
            return int(identifier)
        except (TypeError, ValueError):
            return None
    if str(content.uuid) == str(identifier):
        return content.pk
    return (
        VODContentAlias.objects.filter(
            content_type=content_type, legacy_uuid=identifier
        )
        .values_list("legacy_id", flat=True)
        .first()
    )


def order_sources(relations, order, key=lambda relation: relation.id):
    """Keep the sources a profile offers, in the profile's order."""
    if order is None:
        return relations
    rank = {source: index for index, source in enumerate(order)}
    return sorted(
        (relation for relation in relations if key(relation) in rank),
        key=lambda relation: rank[key(relation)],
    )


def resolution_height(value):
    text = str(value or "").lower()
    if text == "sd":
        return 480
    match = re.fullmatch(r"(\d{3,4})p", text)
    return int(match.group(1)) if match else 0


def build_catalog(profile):
    """Build a new generation and switch to it; the old one serves until then."""
    generation = uuid.uuid4().hex
    signature = catalog_signature(profile)
    VODProfile.objects.filter(pk=profile.pk).update(
        catalog_status=VODProfile.CatalogStatus.BUILDING,
        catalog_started_at=timezone.now(),
        catalog_progress={},
        catalog_error="",
    )
    try:
        counts = {
            content_type: _build_content(profile, generation, content_type)
            for content_type in CONTENT
        }
    except Exception as error:
        VODProfileEntry.objects.filter(profile=profile, generation=generation).delete()
        VODProfile.objects.filter(pk=profile.pk).update(
            catalog_status=VODProfile.CatalogStatus.FAILED,
            catalog_completed_at=timezone.now(),
            catalog_progress={},
            catalog_error=str(error)[:500],
        )
        raise
    with transaction.atomic():
        current = VODProfile.objects.select_for_update().filter(pk=profile.pk).first()
        if current is None:
            return None
        current.catalog_generation = generation
        current.catalog_signature = signature
        current.catalog_counts = counts
        current.catalog_progress = {}
        current.catalog_completed_at = timezone.now()
        # Settings saved during the build need another run.
        current.catalog_status = (
            VODProfile.CatalogStatus.READY
            if catalog_signature(current) == signature
            else VODProfile.CatalogStatus.PENDING
        )
        current.save(
            update_fields=[
                "catalog_generation",
                "catalog_signature",
                "catalog_counts",
                "catalog_progress",
                "catalog_completed_at",
                "catalog_status",
            ]
        )
    VODProfileEntry.objects.filter(profile=profile).exclude(
        generation=generation
    ).delete()
    return counts


def _build_content(profile, generation, content_type):
    select = _title_selector(profile, content_type)
    pending, titles, entries = [], 0, 0
    for content_id, sources in _source_groups(content_type):
        selected, _reason = select(content_id, sources)
        if not selected:
            continue
        titles += 1
        # Entries a client gets in full lists, without per-category extras.
        entries += sum(1 for *_entry, primary in selected if primary)
        pending.extend(selected)
        if len(pending) >= BATCH_SIZE:
            _write(profile, generation, content_type, pending)
            pending = []
            VODProfile.objects.filter(pk=profile.pk).update(
                catalog_progress={"content_type": content_type, "titles": titles}
            )
    if pending:
        _write(profile, generation, content_type, pending)
    return {"titles": titles, "entries": entries}


def _title_selector(profile, content_type, *, explain=False):
    """Return select(content ID, sources) -> (entries, reason it is not offered).

    With explain, select also returns why each left-out source was skipped.
    """
    allowed_category = _category_gate(profile, content_type)
    passes = _source_filter(profile.content_filters)
    excluded = _excluded_content(content_type, profile.content_filters)
    left_out = {
        title["id"]
        for title in profile.excluded_titles
        if title["content_type"] == content_type
    }
    rank = _ranker(profile)
    variants = profile.output_mode == VODProfile.OutputMode.VARIANTS
    # Sources entries list every source; editions only shape Compact entries.
    edition_of = _edition_matcher([] if variants else profile.edition_rules)

    def assess(content_id, sources):
        if content_id in left_out:
            return [], "excluded", {}
        if content_id in excluded:
            return [], "title", {}
        skipped = {}
        eligible = []
        for source in sources:
            if not allowed_category(source.m3u_account_id, source.category_id):
                skipped[source.id] = "category"
            elif not passes(source.metadata):
                skipped[source.id] = "source"
            else:
                eligible.append(source)
        if not eligible:
            reason = (
                "category"
                if all(item == "category" for item in skipped.values())
                else "source"
            )
            return [], reason, skipped
        eligible.sort(key=rank)
        return (
            _content_entries(content_id, eligible, variants, edition_of),
            "",
            skipped,
        )

    if explain:
        return assess
    return lambda content_id, sources: assess(content_id, sources)[:2]


PREVIEW_REASONS = {
    "excluded": "Excluded from this profile.",
    "title": "Excluded by the title filters.",
    "category": "None of its categories is enabled in this profile.",
    "source": "No source matches the content filters.",
}
SOURCE_REASONS = {
    "category": "Category disabled in this profile.",
    "source": "Does not match the content filters.",
}
PREVIEW_CACHE_SECONDS = 120


def preview(
    profile,
    content_type,
    *,
    search="",
    excluded=False,
    account=None,
    category=None,
    page=1,
    page_size=50,
):
    """Show the titles a profile offers, or the ones it excludes, unsaved.

    Offered titles need every matching title evaluated, so their IDs are
    cached briefly for paging.
    """
    from apps.m3u.models import M3UAccount

    from .library import library_settings
    from .models import VODCategory
    from .presentation import canonical_title_search
    from .profiles import (
        GROUP_CATEGORY_NAMES,
        group_category,
        output_name,
        profile_title_expression,
    )

    model, relation_model = CONTENT[content_type]
    languages = library_settings()["languages"]
    group = group_category(profile, content_type) and GROUP_CATEGORY_NAMES[content_type]
    relations = relation_model.objects.filter(m3u_account__is_active=True)
    if account:
        relations = relations.filter(m3u_account_id=account)
    if category:
        relations = relations.filter(category_id=category)
    titles = model.objects.filter(
        library_blocked=False, pk__in=relations.values(f"{content_type}_id")
    )
    if search:
        titles = titles.filter(canonical_title_search("", languages, search))
    if excluded:
        titles = titles.filter(
            pk__in=[
                title["id"]
                for title in profile.excluded_titles
                if title["content_type"] == content_type
            ]
        )
    rows = (
        titles.annotate(_title=profile_title_expression("", profile))
        .order_by(Lower("_title"), "pk")
        .values_list("pk", "_title", "year")
    )
    assess = _title_selector(profile, content_type, explain=True)
    start = (page - 1) * page_size
    if excluded:
        count, rows = rows.count(), list(rows[start : start + page_size])
    else:
        offered = _offered_ids(
            profile, content_type, rows, assess, [search, account, category]
        )
        count, ids = len(offered), offered[start : start + page_size]
        found = {row[0]: row for row in rows.filter(pk__in=ids)}
        rows = [found[pk] for pk in ids if pk in found]

    groups = dict(_source_groups(content_type, [row[0] for row in rows]))
    providers = dict(M3UAccount.objects.values_list("id", "name"))
    categories = dict(
        VODCategory.objects.filter(
            pk__in={
                source.category_id
                for sources in groups.values()
                for source in sources
            }
        ).values_list("id", "name")
    )
    results = []
    for content_id, title, year in rows:
        sources = groups.get(content_id, [])
        by_id = {source.id: source for source in sources}
        entries, reason, skipped = assess(content_id, sources)

        def name(source, edition):
            return output_name(
                profile.name_template,
                title,
                source.metadata,
                year=year,
                edition=edition,
                provider=providers.get(source.m3u_account_id, ""),
                extension=source.extension,
            )

        offered = [entry for entry in entries if entry[-1]]
        roles = {}
        for _id, relation_id, edition, _req, fallbacks, _primary in offered:
            entry_name = name(by_id[relation_id], edition)
            for position, source_id in enumerate(fallbacks):
                roles.setdefault(source_id, (entry_name, position))
        results.append(
            {
                "id": content_id,
                "title": title,
                "year": year,
                "reason": PREVIEW_REASONS.get(reason, ""),
                "excluded": reason == "excluded",
                "entries": [
                    {
                        "name": name(by_id[relation_id], edition),
                        "source_id": relation_id,
                        "edition": edition,
                        "provider": providers.get(
                            by_id[relation_id].m3u_account_id, ""
                        ),
                        "category": group
                        or categories.get(by_id[relation_id].category_id, ""),
                        "fallbacks": fallbacks,
                        "metadata": by_id[relation_id].metadata,
                        "sources": len(fallbacks),
                    }
                    for _id, relation_id, edition, _req, fallbacks, _primary in offered
                ],
                "sources": [
                    {
                        "id": source.id,
                        "provider": providers.get(source.m3u_account_id, ""),
                        "category": categories.get(source.category_id, ""),
                        "metadata": source.metadata,
                        "entry": roles.get(source.id, ("", 0))[0],
                        "state": (
                            ("selected" if roles[source.id][1] == 0 else "fallback")
                            if source.id in roles
                            else "skipped" if source.id in skipped else "unused"
                        ),
                        "reason": SOURCE_REASONS.get(skipped.get(source.id), ""),
                    }
                    for source in sources
                ],
            }
        )
    return {"count": count, "results": results}


def _offered_ids(profile, content_type, rows, assess, query):
    """IDs of the matching titles the profile offers, in title order."""
    key = "vod-profile-preview:" + hashlib.sha256(
        json.dumps(
            [catalog_signature(profile), profile.title_source, content_type]
            + query,
            default=str,
        ).encode()
    ).hexdigest()
    offered = cache.get(key)
    if offered is None:
        offered, chunk = [], []
        for content_id, *_rest in rows.iterator(chunk_size=BATCH_SIZE):
            chunk.append(content_id)
            if len(chunk) == BATCH_SIZE:
                offered.extend(_offered(chunk, content_type, assess))
                chunk = []
        offered.extend(_offered(chunk, content_type, assess))
        cache.set(key, offered, PREVIEW_CACHE_SECONDS)
    return offered


def _offered(content_ids, content_type, assess):
    groups = dict(_source_groups(content_type, content_ids))
    return [
        content_id
        for content_id in content_ids
        if assess(content_id, groups.get(content_id, []))[0]
    ]


def _source_groups(content_type, content_ids=None):
    """Yield (content ID, sources) with each source's effective metadata."""
    _model, relation_model = CONTENT[content_type]
    defaults = {
        (row.m3u_account_id, row.category_id): {
            **legacy_category_metadata(row.custom_properties),
            **(row.metadata_defaults or {}),
        }
        for row in M3UVODCategoryRelation.objects.only(
            "m3u_account_id", "category_id", "custom_properties", "metadata_defaults"
        )
    }
    relations = relation_model.objects.filter(
        m3u_account__is_active=True,
        **{f"{content_type}__library_blocked": False},
    )
    if content_ids is not None:
        relations = relations.filter(**{f"{content_type}_id__in": content_ids})
    fields = [
        "id",
        f"{content_type}_id",
        "category_id",
        "m3u_account_id",
        "m3u_account__priority",
        "declared_metadata",
        "observed_metadata",
        "manual_metadata",
    ]
    if content_type == "movie":
        fields.append("container_extension")
    rows = (
        relations.order_by(f"{content_type}_id", "id")
        .values_list(*fields)
        .iterator(chunk_size=5000)
    )
    current, group = None, []
    for row in rows:
        source = SimpleNamespace(
            id=row[0],
            category_id=row[2],
            m3u_account_id=row[3],
            priority=row[4] or 0,
            custom_properties={},
            declared_metadata=row[5],
            observed_metadata=row[6],
            manual_metadata=row[7],
            extension=row[8] if len(row) > 8 else "",
        )
        # Same lean metadata as the live output, so public IDs stay identical.
        source.metadata = effective_source_metadata(
            source, category_defaults=defaults.get((row[3], row[2]), {})
        )["values"]
        if row[1] != current and group:
            yield current, group
            group = []
        current = row[1]
        group.append(source)
    if group:
        yield current, group


def _category_gate(profile, content_type):
    """Resolve each account category: manual choice, else its import rules."""
    from .profiles import category_rule_states

    choices = {
        choice["relation"]: choice["enabled"] for choice in profile.category_choices
    }
    states = {
        (account, category): choices.get(relation, decision.enabled)
        for relation, account, category, scope, _name, decision in (
            category_rule_states(profile)
        )
        if scope == content_type
    }
    return lambda account, category: states.get((account, category), False)


def _source_filter(filters):
    audio = set(filters.get("audio_languages", []))
    subtitles = set(filters.get("subtitle_languages", []))
    minimum = filters.get("resolution_min", 0)
    maximum = filters.get("resolution_max", 0)
    required = set(filters.get("required_features", []))
    excluded = set(filters.get("excluded_features", []))

    def passes(metadata):
        # Unknown metadata fails closed whenever a filter asks for it.
        if audio and not audio & set(metadata.get("audio_languages", [])):
            return False
        if subtitles and not subtitles & set(metadata.get("subtitle_languages", [])):
            return False
        if minimum or maximum:
            height = resolution_height(metadata.get("resolution"))
            if not height or height < minimum or (maximum and height > maximum):
                return False
        features = set(metadata.get("video_features", []))
        return required <= features and not excluded & features

    return passes


def _excluded_content(content_type, filters):
    """Title-level filters matching the Library's genre, adult and anime filters."""
    model, _relation_model = CONTENT[content_type]
    excluded = set()
    genres = filters.get("excluded_genres", [])
    if genres:
        matching = Q()
        for genre in genres:
            matching |= Q(tmdb_metadata__genres__icontains=genre) | (
                ~Q(tmdb_metadata__has_key="genres") & Q(genre__icontains=genre)
            )
        excluded.update(model.objects.filter(matching).values_list("pk", flat=True))
    adult = Q(tmdb_metadata__adult=True)
    if model is Movie:
        adult |= Q(is_adult=True)
    from .library import missing_tmdb_id

    for mode, condition in (
        (filters.get("anime_mode"), Q(tmdb_metadata__is_anime=True)),
        (filters.get("adult_mode"), adult),
        (filters.get("missing_tmdb_mode"), missing_tmdb_id()),
    ):
        if mode == "exclude":
            excluded.update(
                model.objects.filter(condition).values_list("pk", flat=True)
            )
        elif mode == "only":
            excluded.update(
                model.objects.exclude(condition).values_list("pk", flat=True)
            )
    return excluded


def _ranker(profile):
    audio = {code: index for index, code in enumerate(profile.audio_language_order)}
    subtitles = {
        code: index for index, code in enumerate(profile.subtitle_language_order)
    }
    providers = {account: index for index, account in enumerate(profile.provider_order)}

    def language(order, codes):
        return min((order[code] for code in codes if code in order), default=len(order))

    criteria = {
        "audio_language": lambda source: language(
            audio, source.metadata.get("audio_languages", [])
        ),
        "subtitle_language": lambda source: language(
            subtitles, source.metadata.get("subtitle_languages", [])
        ),
        "provider": lambda source: providers.get(source.m3u_account_id, len(providers)),
        "resolution_desc": lambda source: -resolution_height(
            source.metadata.get("resolution")
        ),
        # Unknown resolutions rank last in both directions.
        "resolution_asc": lambda source: resolution_height(
            source.metadata.get("resolution")
        )
        or 100000,
        "metadata_completeness": lambda source: -sum(
            1 for value in source.metadata.values() if value
        ),
    }
    keys = [criteria[name] for name in profile.ranking]
    # Account priority stays the final tie-breaker, as in the live output.
    return lambda source: (
        *(key(source) for key in keys),
        -source.priority,
        source.id,
    )


def _edition_matcher(rules):
    def edition(metadata):
        height = resolution_height(metadata.get("resolution"))
        audio = set(metadata.get("audio_languages", []))
        subtitles = set(metadata.get("subtitle_languages", []))
        features = set(metadata.get("video_features", []))
        for rule in rules:
            if rule["min_resolution"] and height < rule["min_resolution"]:
                continue
            if rule["max_resolution"] and (
                not height or height > rule["max_resolution"]
            ):
                continue
            if (
                set(rule["required_audio_languages"]) <= audio
                and set(rule["required_subtitle_languages"]) <= subtitles
                and set(rule["required_video_features"]) <= features
            ):
                return rule["title_suffix"]
        return ""

    return edition


def _content_entries(content_id, sources, variants, edition_of):
    """Primary entries plus the best source per category for category requests.

    Sources entries list every provider source on its own, as the provider
    does; each entry plays only its source.
    """
    if variants:
        return [
            (
                content_id,
                source.id,
                "",
                requirements_from_metadata(source.metadata),
                [source.id],
                True,
            )
            for source in sources
        ]
    entries = [
        (content_id, *entry, True) for entry in _title_entries(sources, edition_of)
    ]
    primary = {entry[1] for entry in entries}
    categories = {}
    for source in sources:
        categories.setdefault(source.category_id, []).append(source)
    if len(categories) > 1:
        for members in categories.values():
            entries.extend(
                (content_id, *entry, False)
                for entry in _title_entries(members, edition_of)
                if entry[0] not in primary
            )
    return entries


def _title_entries(sources, edition_of):
    """Split ranked sources into editions (first match) with their fallbacks."""
    editions = {}
    for source in sources:
        editions.setdefault(edition_of(source.metadata), []).append(source)
    for edition, members in editions.items():
        winner = members[0]
        requirements = requirements_from_metadata(winner.metadata)
        fallbacks = [
            source.id
            for source in members
            if metadata_satisfies(source.metadata, requirements)
        ]
        yield winner.id, edition, requirements, fallbacks


def _write(profile, generation, content_type, pending):
    if profile.output_mode == VODProfile.OutputMode.VARIANTS:
        # Each source keeps its own public ID, like a provider catalogue.
        by_source = source_references(
            content_type,
            [(content_id, relation_id) for content_id, relation_id, *_rest in pending],
        )

        def public_id(content_id, relation_id, requirements):
            return by_source[relation_id].legacy_id

    else:
        references = output_references(
            content_type,
            [
                (content_id, requirements)
                for content_id, _id, _ed, requirements, *_rest in pending
            ],
        )

        def public_id(content_id, relation_id, requirements):
            return references[
                selection_key(content_type, content_id, requirements)
            ].legacy_id

    VODProfileEntry.objects.bulk_create(
        [
            VODProfileEntry(
                profile=profile,
                generation=generation,
                content_type=content_type,
                content_id=content_id,
                relation_id=relation_id,
                public_id=public_id(content_id, relation_id, requirements),
                edition=edition,
                source_ids=fallbacks,
                primary=primary,
            )
            for content_id, relation_id, edition, requirements, fallbacks, primary in (
                pending
            )
        ],
        batch_size=BATCH_SIZE,
    )
