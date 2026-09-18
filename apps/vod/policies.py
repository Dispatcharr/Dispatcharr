"""VOD visibility, edition grouping and failover-compatible ranking."""

import hashlib
import re

from django.db.models import Q

from .catalog_cache import catalog_generation, safe_cache_get, safe_cache_set
from .metadata import (
    compatible_video_features,
    normalize_language_list,
    normalize_video_features,
)
from .models import M3UVODCategoryRelation, VODAccessPolicy
from .utils import get_vod_source_name


DEFAULT_EDITION = {
    "key": "default",
    "rule_id": "",
    "name": "",
    "suffix": "",
}

CANONICAL_CONTENT_FILTER_FIELDS = frozenset(
    {
        "required_genres",
        "required_keywords",
        "required_countries",
        "required_age_ratings",
        "min_year",
        "max_year",
        "min_rating",
        "max_rating",
    }
)


def policy_for_user(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    cache_key = f"vod_policy_user:{catalog_generation()}:{user.pk}"
    cached = safe_cache_get(cache_key)
    if cached == 0:
        return None
    if isinstance(cached, VODAccessPolicy):
        return cached
    # A user normally has exactly one profile. If legacy data temporarily
    # contains both the automatically assigned default and an explicit custom
    # profile, the explicit profile must win instead of silently exposing the
    # default catalog.
    assigned = (
        user.vod_access_policies.filter(is_active=True)
        .order_by("is_default", "id")
        .first()
    )
    if assigned:
        safe_cache_set(cache_key, assigned, timeout=3600)
        return assigned
    policy = VODAccessPolicy.objects.filter(
        is_active=True, is_default=True
    ).order_by("id").first()
    if policy and not M3UVODCategoryRelation.objects.filter(
        enabled=True,
        m3u_account__is_active=True,
    ).exists():
        # The source-management migration can precede the first provider
        # refresh that creates category inventory. Keep unassigned users on
        # the original narrow DISTINCT ON output until the default profile has
        # real source boundaries to work with. Explicit assignments above are
        # intentional and therefore take effect immediately.
        policy = None
    safe_cache_set(cache_key, policy or 0, timeout=3600)
    return policy


def enabled_category_map():
    """Global source availability and category defaults, independent of users."""
    cache_key = f"vod_enabled_categories:{catalog_generation()}"
    cached = safe_cache_get(cache_key)
    if isinstance(cached, dict):
        return cached
    mapping = {
        (account_id, category_id): metadata_defaults or {}
        for account_id, category_id, metadata_defaults in (
            M3UVODCategoryRelation.objects.filter(
                enabled=True,
                m3u_account__is_active=True,
            ).values_list("m3u_account_id", "category_id", "metadata_defaults")
        )
    }
    safe_cache_set(cache_key, mapping, timeout=3600)
    return mapping


def _profile_category_rule_matches(rule, category):
    if rule.get("enabled", True) is False:
        return False
    if str(rule.get("scope") or "") != str(
        category.get("category_type") or ""
    ):
        return False
    account_id = rule.get("m3u_account_id")
    if account_id is not None and account_id != "":
        try:
            if int(account_id) != int(category["account_id"]):
                return False
        except (TypeError, ValueError):
            return False
    flags = 0 if rule.get("case_sensitive") else re.IGNORECASE
    try:
        pattern = re.compile(str(rule.get("regex_pattern") or ""), flags)
    except re.error:
        return False
    return bool(pattern.search(str(category.get("category_name") or "")))


def _profile_category_enabled(category, rules):
    """Resolve a globally available category through ordered profile rules."""
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if _profile_category_rule_matches(rule, category):
            return rule.get("action") == "enable"
    return False


def policy_category_map(policy):
    """Return globally enabled sources narrowed by a profile source policy.

    The M3U-account category selection remains an absolute upper boundary.
    Explicit profile rows override dynamic rules, then the first matching
    profile rule wins. Categories without either decision are blocked.
    Profiles from before dynamic rules retain their original semantics: no
    rows means all globally enabled categories, while any saved rows form an
    exact allowlist.
    """
    mapping = enabled_category_map()
    if not policy:
        return mapping
    explicit_rows = list(
        policy.vodpolicycategory_set.all().values_list(
            "category_relation_id",
            "category_relation__m3u_account_id",
            "category_relation__category_id",
            "enabled",
        )
    )
    constraints = policy.hard_constraints or {}
    dynamic_configured = "category_import_rules" in constraints
    if not dynamic_configured:
        if not explicit_rows:
            return mapping
        allowed = {
            (account_id, category_id)
            for _relation_id, account_id, category_id, enabled in explicit_rows
            if enabled
        }
        return {key: value for key, value in mapping.items() if key in allowed}

    explicit_by_relation = {
        relation_id: enabled
        for relation_id, _account_id, _category_id, enabled in explicit_rows
    }
    rules = list(constraints.get("category_import_rules") or [])
    inventory = M3UVODCategoryRelation.objects.filter(
        enabled=True,
        m3u_account__is_active=True,
    ).values(
        "id",
        "m3u_account_id",
        "category_id",
        "category__name",
        "category__category_type",
    )
    allowed = set()
    for category in inventory.iterator(chunk_size=2000):
        key = (category["m3u_account_id"], category["category_id"])
        if key not in mapping:
            continue
        if category["id"] in explicit_by_relation:
            enabled = explicit_by_relation[category["id"]]
        else:
            enabled = _profile_category_enabled(
                {
                    "account_id": category["m3u_account_id"],
                    "category_name": category["category__name"],
                    "category_type": category["category__category_type"],
                },
                rules,
            )
        if enabled:
            allowed.add(key)
    return {key: value for key, value in mapping.items() if key in allowed}


def relation_category_id(relation):
    """Return the provider-category ID for movie, series, or episode relations."""
    if hasattr(relation, "category_id"):
        return relation.category_id
    series_relation = getattr(relation, "series_relation", None)
    return getattr(series_relation, "category_id", None)


def relation_category(relation):
    if hasattr(relation, "category"):
        return relation.category
    series_relation = getattr(relation, "series_relation", None)
    return getattr(series_relation, "category", None)


def allowed_category_query(policy):
    mapping = policy_category_map(policy)
    # Keep upgraded installations usable between the schema migration and
    # their first VOD refresh. Older catalogs can contain movie/series
    # relations before M3UVODCategoryRelation rows have been discovered.
    # Once category inventory exists, it remains the hard visibility boundary.
    if not mapping and not M3UVODCategoryRelation.objects.filter(
        enabled=True,
        m3u_account__is_active=True,
    ).exists():
        return Q()
    if not mapping:
        return Q(pk__in=[])
    query = Q(pk__in=[])
    categories_by_account = {}
    for account_id, category_id in mapping:
        categories_by_account.setdefault(account_id, []).append(category_id)
    for account_id, category_ids in categories_by_account.items():
        query |= Q(m3u_account_id=account_id, category_id__in=category_ids)
    return query


def _language_set(value):
    return set(normalize_language_list(value))


def _vertical_resolution(metadata):
    value = (
        metadata.get("height")
        or metadata.get("resolution")
        or metadata.get("quality")
    )
    if isinstance(value, dict):
        value = value.get("height") or value.get("resolution")
    text = str(value or "").lower()
    for candidate in (4320, 2160, 1440, 1080, 720, 576, 540, 480, 360, 240):
        if str(candidate) in text:
            return candidate
    return 0


def _constraint_int(constraints, key):
    try:
        return max(0, int(constraints.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def relation_metadata(relation, category_relation=None):
    defaults = (
        category_relation
        if isinstance(category_relation, dict)
        else category_relation.metadata_defaults if category_relation else {}
    )
    from .metadata import relation_declared_metadata

    declared = relation_declared_metadata(relation)
    return relation.effective_metadata(
        category_defaults=defaults,
        relation_declared=declared,
    )["values"]


_METADATA_NOT_PROVIDED = object()


def _relation_source_name(relation):
    content = (
        getattr(relation, "movie", None)
        or getattr(relation, "series", None)
        or getattr(relation, "episode", None)
    )
    return get_vod_source_name(
        relation,
        getattr(content, "name", "") or "",
    )


def _canonical_content(relation):
    """Return the canonical movie/series represented by a source relation."""
    content = getattr(relation, "movie", None) or getattr(relation, "series", None)
    if content is not None:
        return content
    episode = getattr(relation, "episode", None)
    if episode is not None:
        return getattr(episode, "series", None)
    series_relation = getattr(relation, "series_relation", None)
    return getattr(series_relation, "series", None)


def _metadata_text_values(value):
    """Flatten common provider/TMDB list shapes into non-empty strings."""
    if value in (None, "", [], {}):
        return []
    if isinstance(value, dict):
        value = value.get("name") or value.get("value") or ""
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_metadata_text_values(item))
        return values
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _canonical_filter_metadata(relation):
    """Return reusable canonical metadata for profile content rules.

    External IDs are intentionally omitted. They identify one title and belong
    to matching/administration, not to reusable output-profile rules.
    """
    content = _canonical_content(relation)
    if content is None:
        return {
            "genres": [],
            "keywords": [],
            "countries": [],
            "age_ratings": [],
            "year": None,
            "rating": None,
            "is_anime": False,
            "is_adult": False,
            "metadata_available": False,
            "tmdb_available": False,
        }
    tmdb_metadata = (
        content.tmdb_metadata
        if isinstance(getattr(content, "tmdb_metadata", None), dict)
        else {}
    )
    from .tmdb import apply_manual_overrides

    tmdb_metadata = apply_manual_overrides(
        tmdb_metadata,
        tmdb_metadata.get("_manual_overrides") or {},
    )
    properties = (
        content.custom_properties
        if isinstance(getattr(content, "custom_properties", None), dict)
        else {}
    )
    genres = _metadata_text_values(tmdb_metadata.get("genres"))
    if not genres:
        genres = _metadata_text_values(getattr(content, "genre", ""))
    countries = _metadata_text_values(tmdb_metadata.get("country"))
    if not countries:
        countries = _metadata_text_values(properties.get("country"))
    age_ratings = _metadata_text_values(tmdb_metadata.get("age_rating"))
    if not age_ratings:
        age_ratings = _metadata_text_values(
            properties.get("age_rating") or properties.get("age")
        )
    release_date = str(tmdb_metadata.get("release_date") or "")
    year = getattr(content, "year", None)
    if not year and len(release_date) >= 4 and release_date[:4].isdigit():
        year = int(release_date[:4])
    raw_rating = tmdb_metadata.get("rating")
    if raw_rating in (None, ""):
        raw_rating = getattr(content, "rating", None)
    try:
        rating = float(raw_rating) if raw_rating not in (None, "") else None
    except (TypeError, ValueError):
        rating = None
    return {
        "genres": genres,
        "keywords": _metadata_text_values(tmdb_metadata.get("keywords")),
        "countries": countries,
        "age_ratings": age_ratings,
        "year": year,
        "rating": rating,
        "is_anime": bool(tmdb_metadata.get("is_anime", False)),
        "is_adult": bool(
            tmdb_metadata.get("adult", False)
            or getattr(content, "is_adult", False)
        ),
        "metadata_available": bool(
            tmdb_metadata
            or getattr(content, "tmdb_status", "") in {"matched", "manual"}
        ),
        "tmdb_available": bool(
            getattr(content, "tmdb_match_id", "")
            or getattr(content, "tmdb_id", "")
            or tmdb_metadata.get("id")
        ),
    }


def _contains_any(observed, requested):
    observed = {
        str(value).strip().casefold() for value in observed if str(value).strip()
    }
    requested = {
        str(value).strip().casefold() for value in requested if str(value).strip()
    }
    if not requested:
        return True
    return not requested.isdisjoint(observed)


def _mode_matches(mode, observed):
    if mode in (None, "", "any"):
        return True
    return bool(observed) is (str(mode).lower() == "yes")


def _rule_uses_canonical_metadata(rule):
    return (
        any(
            rule.get(field) not in (None, "", 0, 0.0, [], {})
            for field in CANONICAL_CONTENT_FILTER_FIELDS
        )
        or rule.get("anime_mode") in {"yes", "no"}
        or rule.get("adult_mode") in {"yes", "no"}
        or rule.get("metadata_mode") in {"available", "missing"}
        or rule.get("tmdb_mode") in {"available", "missing"}
    )


def content_rules_use_canonical_metadata(rules):
    return any(
        isinstance(rule, dict)
        and rule.get("enabled", True) is not False
        and _rule_uses_canonical_metadata(rule)
        for rule in rules or []
    )


def _canonical_content_filter_matches(rule, metadata):
    for rule_key, metadata_key in (
        ("required_genres", "genres"),
        ("required_keywords", "keywords"),
        ("required_countries", "countries"),
        ("required_age_ratings", "age_ratings"),
    ):
        if not _contains_any(metadata[metadata_key], rule.get(rule_key) or []):
            return False

    if not _mode_matches(rule.get("anime_mode"), metadata["is_anime"]):
        return False
    if not _mode_matches(rule.get("adult_mode"), metadata["is_adult"]):
        return False
    metadata_mode = str(rule.get("metadata_mode") or "any")
    if metadata_mode == "available" and not metadata["metadata_available"]:
        return False
    if metadata_mode == "missing" and metadata["metadata_available"]:
        return False
    tmdb_mode = str(rule.get("tmdb_mode") or "any")
    if tmdb_mode == "available" and not metadata["tmdb_available"]:
        return False
    if tmdb_mode == "missing" and metadata["tmdb_available"]:
        return False

    year = metadata["year"]
    min_year = _constraint_int(rule, "min_year")
    max_year = _constraint_int(rule, "max_year")
    if (min_year or max_year) and not year:
        return False
    if min_year and year < min_year:
        return False
    if max_year and year > max_year:
        return False

    rating = metadata["rating"]
    try:
        min_rating = float(rule.get("min_rating") or 0)
        max_rating = float(rule.get("max_rating") or 0)
    except (TypeError, ValueError):
        return False
    if (min_rating or max_rating) and rating is None:
        return False
    if min_rating and rating < min_rating:
        return False
    if max_rating and rating > max_rating:
        return False
    return True


def _stream_filter_metadata_matches(rule, metadata):
    required_audio = _language_set(rule.get("required_audio_languages"))
    observed_audio = _language_set(
        metadata.get("audio_languages") or metadata.get("languages")
    )
    if required_audio and required_audio.isdisjoint(observed_audio):
        return False

    required_subtitles = _language_set(rule.get("required_subtitle_languages"))
    observed_subtitles = _language_set(metadata.get("subtitle_languages"))
    if required_subtitles and required_subtitles.isdisjoint(observed_subtitles):
        return False

    required_features = set(
        normalize_video_features(rule.get("required_video_features"))
    )
    if required_features:
        observed_features = set(
            normalize_video_features(metadata.get("video_features"))
        )
        compatible_required = {
            compatible
            for required in required_features
            for compatible in compatible_video_features(required)
        }
        if compatible_required.isdisjoint(observed_features):
            return False
    min_resolution = _constraint_int(rule, "min_resolution")
    max_resolution = _constraint_int(rule, "max_resolution")
    resolution = _vertical_resolution(metadata)
    if (min_resolution or max_resolution) and not resolution:
        return False
    if min_resolution and resolution < min_resolution:
        return False
    if max_resolution and resolution > max_resolution:
        return False
    return True


def _edition_match_relation(relation):
    """Use the parent series source when classifying an episode edition."""
    return getattr(relation, "series_relation", None) or relation


def _edition_rule_matches(relation, rule, metadata):
    min_resolution = _constraint_int(rule, "min_resolution")
    max_resolution = _constraint_int(rule, "max_resolution")
    resolution = _vertical_resolution(metadata)
    if (min_resolution or max_resolution) and not resolution:
        return False
    if min_resolution and resolution < min_resolution:
        return False
    if max_resolution and resolution > max_resolution:
        return False

    required_audio = _language_set(rule.get("required_audio_languages"))
    observed_audio = _language_set(
        metadata.get("audio_languages") or metadata.get("languages")
    )
    if required_audio and required_audio.isdisjoint(observed_audio):
        return False
    required_subtitles = _language_set(rule.get("required_subtitle_languages"))
    observed_subtitles = _language_set(metadata.get("subtitle_languages"))
    if required_subtitles and required_subtitles.isdisjoint(observed_subtitles):
        return False

    observed_features = set(
        normalize_video_features(metadata.get("video_features"))
    )
    for required in normalize_video_features(
        rule.get("required_video_features")
    ):
        if set(compatible_video_features(required)).isdisjoint(observed_features):
            return False
    return True


def relation_edition(
    relation,
    policy,
    category_mapping=None,
    metadata=_METADATA_NOT_PROVIDED,
):
    """Return the first matching profile edition for a concrete source.

    Editions are deliberately independent from provider categories. The
    ``default`` key is the catch-all bucket for unmatched sources.
    """
    rules = list((policy.edition_rules if policy else None) or [])
    if not rules:
        return dict(DEFAULT_EDITION)
    source_relation = _edition_match_relation(relation)
    category_mapping = category_mapping or policy_category_map(policy)
    if metadata is _METADATA_NOT_PROVIDED or source_relation is not relation:
        category_relation = category_mapping.get(
            (
                source_relation.m3u_account_id,
                relation_category_id(source_relation),
            )
        )
        metadata = relation_metadata(source_relation, category_relation)
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or rule.get("enabled", True) is False:
            continue
        if not _edition_rule_matches(source_relation, rule, metadata):
            continue
        rule_id = str(rule.get("id") or index)
        key = "ed:" + hashlib.sha1(rule_id.encode("utf-8")).hexdigest()
        return {
            "key": key,
            "rule_id": rule_id,
            "name": str(
                rule.get("title_suffix") or rule.get("name") or ""
            )[:120],
            "suffix": str(
                rule.get("title_suffix") or rule.get("name") or ""
            )[:120],
        }
    return dict(DEFAULT_EDITION)


def relation_stream_filter_match(relation, policy, metadata):
    """Return ``(rule_id, decision)`` for the first matching content filter."""
    rules = ((policy.hard_constraints if policy else None) or {}).get(
        "source_rules", []
    )
    rules = [
        rule
        for rule in rules if isinstance(rule, dict) and rule.get("match_field")
    ]
    if not rules:
        return None

    cache_key = repr(rules)
    compiled_cache = getattr(policy, "_compiled_vod_stream_filters", None)
    if not compiled_cache or compiled_cache[0] != cache_key:
        compiled = []
        for rule in rules:
            if rule.get("enabled", True) is False:
                continue
            flags = 0 if rule.get("case_sensitive") else re.IGNORECASE
            try:
                compiled.append(
                    (re.compile(str(rule.get("regex_pattern") or ""), flags), rule)
                )
            except re.error:
                continue
        compiled_cache = (cache_key, compiled)
        setattr(policy, "_compiled_vod_stream_filters", compiled_cache)

    category = relation_category(relation)
    targets = {
        "category": getattr(category, "name", "") or "",
        "stream": _relation_source_name(relation),
    }
    canonical_metadata = None
    for pattern, rule in compiled_cache[1]:
        if pattern.search(targets.get(rule.get("match_field"), "")) is None:
            continue
        if not _stream_filter_metadata_matches(rule, metadata):
            continue
        if _rule_uses_canonical_metadata(rule):
            if canonical_metadata is None:
                canonical_metadata = _canonical_filter_metadata(relation)
            if not _canonical_content_filter_matches(rule, canonical_metadata):
                continue
        return (
            str(rule.get("id") or ""),
            rule.get("result", "include") != "exclude",
        )
    return None


def relation_stream_filter_result(relation, policy, metadata):
    """Return the first matching ordered VOD content-filter decision."""
    match = relation_stream_filter_match(relation, policy, metadata)
    return match[1] if match is not None else None


def relation_constraints(relation, policy):
    """Return global constraints with the first matching source rule applied."""
    constraints = dict((policy.hard_constraints if policy else None) or {})
    rules = constraints.pop("source_rules", [])
    if not policy or not rules:
        return constraints
    category = relation_category(relation)
    category_name = getattr(category, "name", "") or ""
    cache_key = repr(rules)
    compiled_cache = getattr(policy, "_compiled_source_rules", None)
    if not compiled_cache or compiled_cache[0] != cache_key:
        compiled_rules = []
        for rule in rules if isinstance(rules, list) else []:
            if (
                not isinstance(rule, dict)
                or rule.get("enabled", True) is False
                or rule.get("match_field")
            ):
                continue
            pattern = str(rule.get("category_regex") or ".*")
            flags = 0 if rule.get("case_sensitive") else re.IGNORECASE
            try:
                compiled_rules.append((re.compile(pattern, flags), rule))
            except re.error:
                continue
        compiled_cache = (cache_key, compiled_rules)
        setattr(policy, "_compiled_source_rules", compiled_cache)
    for pattern, rule in compiled_cache[1]:
        if pattern.search(category_name) is None:
            continue
        return {
            **constraints,
            **{
                key: value
                for key, value in rule.items()
                if key
                not in {
                    "id",
                    "name",
                    "category_regex",
                    "case_sensitive",
                    "enabled",
                }
            },
        }
    return constraints


def relation_allowed(
    relation,
    policy,
    category_mapping=None,
    metadata=_METADATA_NOT_PROVIDED,
):
    return relation_policy_evaluation(
        relation,
        policy,
        category_mapping=category_mapping,
        metadata=metadata,
    )["allowed"]


def relation_policy_evaluation(
    relation,
    policy,
    category_mapping=None,
    metadata=_METADATA_NOT_PROVIDED,
):
    """Explain the same hard decision used by output and failover selection.

    The compact-source preview must never maintain a second approximation of
    the access rules.  Returning a stable reason code here lets every caller
    use the production decision while still explaining why a source is greyed
    out in the UI.
    """
    if not policy:
        return {"allowed": True, "reason": "eligible", "rule_id": ""}
    category_mapping = category_mapping or policy_category_map(policy)
    category_relation = category_mapping.get(
        (relation.m3u_account_id, relation_category_id(relation))
    )
    if category_relation is None and category_mapping:
        return {
            "allowed": False,
            "reason": "category_not_allowed",
            "rule_id": "",
        }

    if metadata is _METADATA_NOT_PROVIDED:
        metadata = relation_metadata(relation, category_relation)
    stream_filter_match = relation_stream_filter_match(relation, policy, metadata)
    if stream_filter_match is not None:
        rule_id, decision = stream_filter_match
        return {
            "allowed": decision,
            "reason": (
                "stream_filter_include" if decision else "stream_filter_exclude"
            ),
            "rule_id": rule_id,
        }
    content_rules = [
        rule
        for rule in ((policy.hard_constraints or {}).get("source_rules") or [])
        if isinstance(rule, dict) and rule.get("enabled", True) is not False
    ]
    if content_rules and (policy.hard_constraints or {}).get(
        "content_default_action", "include"
    ) == "exclude":
        return {
            "allowed": False,
            "reason": "content_filter_default_exclude",
            "rule_id": "",
        }
    constraints = relation_constraints(relation, policy)
    allow_unknown = constraints.get("allow_unknown_metadata", True)

    required_audio = _language_set(constraints.get("required_audio_languages"))
    observed_audio = _language_set(
        metadata.get("audio_languages") or metadata.get("languages")
    )
    required_subtitles = _language_set(
        constraints.get("required_subtitle_languages")
    )
    observed_subtitles = _language_set(metadata.get("subtitle_languages"))
    excluded_audio = _language_set(constraints.get("excluded_audio_languages"))
    excluded_subtitles = _language_set(
        constraints.get("excluded_subtitle_languages")
    )
    if excluded_audio and not excluded_audio.isdisjoint(observed_audio):
        return {"allowed": False, "reason": "audio_excluded", "rule_id": ""}
    if excluded_subtitles and not excluded_subtitles.isdisjoint(
        observed_subtitles
    ):
        return {
            "allowed": False,
            "reason": "subtitle_excluded",
            "rule_id": "",
        }
    language_mode = constraints.get("language_match_mode", "all")
    language_checks = []
    if required_audio:
        language_checks.append(
            None
            if not observed_audio
            else not required_audio.isdisjoint(observed_audio)
        )
    if required_subtitles:
        language_checks.append(
            None
            if not observed_subtitles
            else not required_subtitles.isdisjoint(observed_subtitles)
        )
    if language_checks:
        known_checks = [value for value in language_checks if value is not None]
        if language_mode == "any":
            # A known match is sufficient. A known non-match is not rescued by
            # another unknown field; this prevents ENG audio with unclassified
            # subtitles from leaking into a GER policy.
            if known_checks and not any(known_checks):
                return {
                    "allowed": False,
                    "reason": "language_not_matched",
                    "rule_id": "",
                }
            if not known_checks and not allow_unknown:
                return {
                    "allowed": False,
                    "reason": "language_unknown",
                    "rule_id": "",
                }
        else:
            if any(value is False for value in language_checks):
                return {
                    "allowed": False,
                    "reason": "language_not_matched",
                    "rule_id": "",
                }
            if (
                any(value is None for value in language_checks)
                and not allow_unknown
            ):
                return {
                    "allowed": False,
                    "reason": "language_unknown",
                    "rule_id": "",
                }

    resolution = _vertical_resolution(metadata)
    min_resolution = _constraint_int(constraints, "min_resolution")
    max_resolution = _constraint_int(constraints, "max_resolution")
    if min_resolution and not resolution and not allow_unknown:
        return {
            "allowed": False,
            "reason": "resolution_unknown",
            "rule_id": "",
        }
    if min_resolution and resolution and resolution < min_resolution:
        return {
            "allowed": False,
            "reason": "resolution_below_minimum",
            "rule_id": "",
        }
    if max_resolution and resolution and resolution > max_resolution:
        return {
            "allowed": False,
            "reason": "resolution_above_maximum",
            "rule_id": "",
        }
    required_features = set(
        normalize_video_features(constraints.get("required_video_features"))
    )
    observed_features = set(normalize_video_features(metadata.get("video_features")))
    excluded_features = set(
        normalize_video_features(constraints.get("excluded_video_features"))
    )
    if excluded_features and not excluded_features.isdisjoint(observed_features):
        return {"allowed": False, "reason": "feature_excluded", "rule_id": ""}
    if required_features:
        if not observed_features and not allow_unknown:
            return {
                "allowed": False,
                "reason": "feature_unknown",
                "rule_id": "",
            }
        compatible_required = {
            compatible
            for required in required_features
            for compatible in compatible_video_features(required)
        }
        feature_match = not compatible_required.isdisjoint(observed_features)
        if observed_features and not feature_match:
            return {
                "allowed": False,
                "reason": "feature_not_matched",
                "rule_id": "",
            }
    return {"allowed": True, "reason": "eligible", "rule_id": ""}


def _preference_score(observed, preferred):
    preferred = normalize_language_list(preferred)
    observed = _language_set(observed)
    if not preferred:
        return 0
    for index, code in enumerate(preferred):
        if code in observed:
            return len(preferred) - index
    return 0


def _metadata_completeness(metadata):
    """Small, deterministic score used only after higher ranking criteria."""
    return sum(
        (
            bool(metadata.get("audio_languages") or metadata.get("languages")),
            bool(metadata.get("subtitle_languages")),
            bool(_vertical_resolution(metadata)),
            bool(metadata.get("container_extension")),
            bool(metadata.get("video_features")),
        )
    )


def _provider_preference_score(policy, account_id):
    """Rank listed providers without querying or excluding unlisted accounts."""
    order = tuple((policy.provider_order if policy else None) or ())
    cached = getattr(policy, "_vod_provider_preference", None) if policy else None
    if not cached or cached[0] != order:
        normalized = []
        for raw_account_id in order:
            try:
                provider_id = int(raw_account_id)
            except (TypeError, ValueError):
                continue
            if provider_id > 0 and provider_id not in normalized:
                normalized.append(provider_id)
        scores = {
            provider_id: len(normalized) - index
            for index, provider_id in enumerate(normalized)
        }
        cached = (order, scores)
        if policy:
            setattr(policy, "_vod_provider_preference", cached)
    return cached[1].get(account_id, 0) if cached else 0


def relation_rank(
    relation,
    category_mapping,
    policy=None,
    metadata=_METADATA_NOT_PROVIDED,
):
    category_relation = category_mapping.get(
        (relation.m3u_account_id, relation_category_id(relation))
    )
    if metadata is _METADATA_NOT_PROVIDED:
        metadata = relation_metadata(
            relation,
            category_relation,
        )
    constraints = relation_constraints(relation, policy)
    resolution = _vertical_resolution(metadata)
    dimensions = {
        "audio_language": _preference_score(
            metadata.get("audio_languages") or metadata.get("languages"),
            constraints.get("audio_language_order")
            or constraints.get("required_audio_languages"),
        ),
        "subtitle_language": _preference_score(
            metadata.get("subtitle_languages"),
            constraints.get("subtitle_language_order")
            or constraints.get("required_subtitle_languages"),
        ),
        "provider": _provider_preference_score(policy, relation.m3u_account_id),
        # Existing policies used "resolution". Keep it as a high-first alias.
        "resolution": resolution,
        "resolution_desc": resolution,
        # Ranking is sorted descending. Known low resolutions therefore get a
        # higher inverted score, while unknown metadata remains last.
        "resolution_asc": 10000 - resolution if resolution else -1,
        "metadata_completeness": _metadata_completeness(metadata),
    }
    requested = [
        "resolution_desc" if key == "resolution" else key
        for key in list((policy.ranking if policy else None) or [])
    ]
    disabled = {
        "resolution_desc" if key == "resolution" else key
        for key in constraints.get("disabled_ranking", [])
    }
    requested_resolution = next(
        (
            key for key in requested
            if key in {"resolution_desc", "resolution_asc"}
        ),
        None,
    )
    requested = [
        key for key in requested
        if (
            key not in {"resolution_desc", "resolution_asc"}
            or key == requested_resolution
        )
    ]
    allowed_order = [
        "audio_language",
        "subtitle_language",
        "provider",
        requested_resolution or "resolution_desc",
        "metadata_completeness",
    ]
    order = list(
        dict.fromkeys(
            [
                key for key in requested + allowed_order
                if key in dimensions and key not in disabled
            ]
        )
    )
    return (
        *(dimensions[key] for key in order),
        relation.m3u_account.priority,
        -relation.id,
    )


def select_relations_for_policy(relations, policy, canonical_field):
    """Select allowed variants or one highest-ranked relation per title."""
    if not policy:
        return list(relations)
    category_mapping = policy_category_map(policy)
    selected = {}
    for relation in relations:
        category_relation = category_mapping.get(
            (relation.m3u_account_id, relation_category_id(relation))
        )
        metadata = relation_metadata(relation, category_relation)
        if not relation_allowed(
            relation,
            policy,
            category_mapping,
            metadata=metadata,
        ):
            continue
        key = _relation_selection_key(
            relation,
            policy,
            canonical_field,
            metadata=metadata,
            category_mapping=category_mapping,
        )
        rank = relation_rank(
            relation,
            category_mapping,
            policy,
            metadata=metadata,
        )
        current = selected.get(key)
        if current is None or rank > current[0]:
            selected[key] = (rank, relation)

    selected_relations = [entry[1] for entry in selected.values()]
    return sorted(
        selected_relations,
        key=lambda relation: (
            str(getattr(relation, canonical_field)),
            tuple(
                -value
                for value in relation_rank(
                    relation, category_mapping, policy
                )[:-1]
            ),
            relation.id,
        ),
    )


def _relation_selection_key(
    relation,
    policy,
    canonical_field,
    *,
    metadata=_METADATA_NOT_PROVIDED,
    category_mapping=None,
):
    if policy.export_mode == VODAccessPolicy.ExportMode.COMPACT:
        edition = relation_edition(
            relation,
            policy,
            category_mapping=category_mapping,
            metadata=metadata,
        )
        return (
            "canonical",
            getattr(relation, canonical_field),
            edition["key"],
        )
    # Variants output is deliberately one-to-one: selecting an entry in
    # the client must identify the exact provider relation represented by that
    # entry. Two provider relations must never collapse into one client item.
    return ("relation", relation.id)


def select_relation_ids_for_policy(
    relations,
    policy,
    canonical_field,
    stats=None,
    progress_callback=None,
    progress_interval=5000,
    output_category_ids=None,
):
    """Stream relations and retain only the winning ID for each output entry.

    This is the cold-cache XC path. Keeping compact winner tuples instead of a
    list of every ORM object prevents large VOD libraries from being duplicated
    in memory while policy constraints and ranking are evaluated. Compact
    callers may pass ``output_category_ids`` to keep every suffix split for a
    canonical title in one existing source category.
    """
    if not policy:
        relation_ids = [relation.id for relation in relations]
        if stats is not None:
            stats.update(
                candidates=len(relation_ids),
                eligible=len(relation_ids),
                selected=len(relation_ids),
            )
        return relation_ids

    category_mapping = policy_category_map(policy)
    selected = {}
    candidate_count = 0
    eligible_count = 0
    for relation in relations:
        candidate_count += 1
        if (
            progress_callback
            and candidate_count % max(int(progress_interval or 1), 1) == 0
        ):
            progress_callback(candidate_count)
        category_relation = category_mapping.get(
            (relation.m3u_account_id, relation_category_id(relation))
        )
        metadata = relation_metadata(relation, category_relation)
        if not relation_allowed(
            relation,
            policy,
            category_mapping,
            metadata=metadata,
        ):
            continue
        eligible_count += 1
        key = _relation_selection_key(
            relation,
            policy,
            canonical_field,
            metadata=metadata,
            category_mapping=category_mapping,
        )
        rank = relation_rank(
            relation,
            category_mapping,
            policy,
            metadata=metadata,
        )
        current = selected.get(key)
        if current is None or rank > current[0]:
            selected[key] = (
                rank,
                relation.id,
                relation_category_id(relation),
            )

    if (
        output_category_ids is not None
        and policy.export_mode == VODAccessPolicy.ExportMode.COMPACT
    ):
        category_winners = {}
        for key, entry in selected.items():
            canonical_id = key[1]
            is_default = key[2] == DEFAULT_EDITION["key"]
            current = category_winners.get(canonical_id)
            if (
                current is None
                or (is_default and not current[0])
                or (is_default == current[0] and entry[0] > current[1])
            ):
                category_winners[canonical_id] = (
                    is_default,
                    entry[0],
                    entry[2],
                )
        output_category_ids.update(
            {
                canonical_id: entry[2]
                for canonical_id, entry in category_winners.items()
            }
        )

    relation_ids = [entry[1] for entry in selected.values()]
    if stats is not None:
        stats.update(
            candidates=candidate_count,
            eligible=eligible_count,
            selected=len(relation_ids),
        )
    return relation_ids


def ordered_failover_candidates(candidates, policy, preferred_relation=None):
    """Apply the same hard constraints and ranking used by Compact output."""
    if not policy:
        return list(candidates)
    category_mapping = policy_category_map(policy)
    ranked = []
    preferred_edition_key = None
    if preferred_relation is not None and policy.edition_rules:
        preferred_edition_key = relation_edition(
            preferred_relation,
            policy,
            category_mapping=category_mapping,
        )["key"]
    for relation in candidates:
        category_relation = category_mapping.get(
            (relation.m3u_account_id, relation_category_id(relation))
        )
        metadata = relation_metadata(relation, category_relation)
        if not relation_allowed(
            relation,
            policy,
            category_mapping,
            metadata=metadata,
        ):
            continue
        if (
            preferred_edition_key is not None
            and relation_edition(
                relation,
                policy,
                category_mapping=category_mapping,
                metadata=metadata,
            )["key"]
            != preferred_edition_key
        ):
            continue
        ranked.append(
            (
                relation_rank(
                    relation,
                    category_mapping,
                    policy,
                    metadata=metadata,
                ),
                relation,
            )
        )
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    return [entry[1] for entry in ranked]


def ordered_candidates(candidates, policy, preferred_relation=None):
    """Return playback candidates for the selected output entry.

    Compact output represents a canonical title and therefore walks its
    ranked fallback sources. Variants output represents one concrete
    provider relation, so it may only play that exact relation.
    """
    if not candidates:
        return []
    if (
        policy
        and policy.export_mode == VODAccessPolicy.ExportMode.VARIANTS
        and preferred_relation is not None
    ):
        return (
            [preferred_relation]
            if relation_allowed(preferred_relation, policy)
            else []
        )
    if not policy:
        ordered = list(candidates)
    else:
        ordered = ordered_failover_candidates(
            candidates,
            policy,
            preferred_relation=preferred_relation,
        )
    if preferred_relation and any(
        candidate.id == preferred_relation.id for candidate in ordered
    ):
        return [preferred_relation] + [
            candidate
            for candidate in ordered
            if candidate.id != preferred_relation.id
        ]
    return ordered
