"""VOD profile rules: validation and the profile that applies to a user."""

import string

from django.db import transaction

from .metadata import normalize_languages, normalize_video_feature
from .models import (
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODProfile,
    VODProfileAssignment,
    VODProfileCategoryRule,
)

RANKING_CRITERIA = (
    "audio_language",
    "subtitle_language",
    "provider",
    "resolution_desc",
    "resolution_asc",
    "metadata_completeness",
)
NAME_PLACEHOLDERS = frozenset(
    {
        "title",
        "year",
        "edition",
        "provider",
        "dub",
        "sub",
        "resolution",
        "format",
        "features",
    }
)
CONTENT_MODES = ("", "exclude", "only")
# Title sources besides the Library metadata languages.
PROVIDER_TITLES = "provider"
CLEAN_TITLES = "clean"
# One client category per content type, as the prototype used.
GROUP_CATEGORY_IDS = {"movie": 2_000_000_000, "series": 2_000_000_001}
GROUP_CATEGORY_NAMES = {"movie": "Movies", "series": "Series"}
TITLE_MODELS = {"movie": Movie, "series": Series}
MAX_RULES = 100
MAX_LIST_ITEMS = 50
MAX_TEXT = 120


class FieldError(ValueError):
    """A validation message for one field, optionally of one ordered rule."""

    def __init__(self, field, message, index=None):
        super().__init__(message)
        self.field = field
        self.index = index


def default_profile():
    """Return the default profile, recreating it if an install lost it."""
    profile = VODProfile.objects.filter(is_default=True).first()
    if profile is not None:
        return profile
    with transaction.atomic():
        profile, created = VODProfile.objects.get_or_create(
            is_default=True,
            defaults={"name": _free_name("Default"), "ranking": ["provider"]},
        )
        if created:
            # Like the migration: offer every category the accounts enable.
            VODProfileCategoryRule.objects.bulk_create(
                VODProfileCategoryRule(
                    profile=profile, scope=scope, regex_pattern=".*", action="enable"
                )
                for scope in VODProfileCategoryRule.Scope.values
            )
    return profile


def _free_name(name):
    candidate, index = name, 2
    while VODProfile.objects.filter(name=candidate).exists():
        candidate, index = f"{name} {index}", index + 1
    return candidate


def profile_languages(profile):
    """Title languages: the Library languages, starting with the profile's."""
    from .library import library_settings

    if profile.title_source == CLEAN_TITLES:
        return []
    languages = library_settings()["languages"]
    if profile.title_source not in languages:
        return languages
    return [profile.title_source] + [
        language for language in languages if language != profile.title_source
    ]


def profile_title(profile, content, provider_title):
    """The title clients get, as the provider names it or from the Library."""
    from .presentation import canonical_title

    if profile.title_source == PROVIDER_TITLES:
        return provider_title
    return canonical_title(content, profile_languages(profile))


def profile_title_expression(prefix, profile):
    """profile_title in SQL, with the provider's title stored on the content."""
    from django.db.models import F

    from .presentation import canonical_title_expression

    if profile.title_source == PROVIDER_TITLES:
        return F(f"{prefix}name")
    return canonical_title_expression(prefix, profile_languages(profile))


def library_metadata_language(profile):
    """Language of Library descriptions: the title language, else the first."""
    from .library import library_settings

    languages = library_settings()["languages"]
    return profile.title_source if profile.title_source in languages else languages[0]


def uses_enriched_metadata(profile):
    return profile.metadata_source == VODProfile.MetadataSource.ENRICHED


def group_category(profile, content_type):
    """The single client category of grouped output, else None."""
    if profile.output_groups != VODProfile.OutputGroups.MOVIE_SERIES:
        return None
    return GROUP_CATEGORY_IDS[content_type]


def category_rule_states(profile, rules=None, *, enabled_only=False):
    """Yield (relation, account, category, scope, name, decision) per category.

    The decision comes from the first matching enabled import rule, exactly as
    for M3U imports; categories without a matching rule are disabled.
    """
    from apps.m3u.group_rules import compile_group_rules, evaluate_group_rules

    if rules is None:
        rules = profile.category_rules.all() if profile.pk else []
    rules = sorted(rules, key=lambda rule: (rule.order, str(rule.id)))
    compiled = {
        scope: compile_group_rules([rule for rule in rules if rule.scope == scope])
        for scope in VODProfileCategoryRule.Scope.values
    }
    relations = M3UVODCategoryRelation.objects.filter(
        category__category_type__in=compiled
    )
    if enabled_only:
        relations = relations.filter(enabled=True)
    for relation, account, category, scope, name in (
        relations.order_by("id")
        .values_list(
            "pk",
            "m3u_account_id",
            "category_id",
            "category__category_type",
            "category__name",
        )
    ):
        yield relation, account, category, scope, name, evaluate_group_rules(
            compiled[scope], group_name=name
        )


def profile_for_user(user):
    """An active assigned profile wins; everyone else uses the default."""
    assignment = (
        VODProfileAssignment.objects.select_related("profile")
        .filter(user_id=getattr(user, "pk", None), profile__is_active=True)
        .first()
    )
    return assignment.profile if assignment else default_profile()


def _height(value, field):
    if value in (None, ""):
        return 0
    try:
        height = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a pixel height such as 2160.")
    if not 0 <= height <= 20000:
        raise ValueError(f"{field} must be between 0 and 20000.")
    return height


def _text(value, field, *, required=False):
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"Enter {field}.")
    if len(text) > MAX_TEXT:
        raise ValueError(f"{field.capitalize()} is too long.")
    return text


def _list(value, field):
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
        raise ValueError(f"{field.capitalize()} must be a short list.")
    return value


def _features(value, field):
    return list(
        dict.fromkeys(normalize_video_feature(item) for item in _list(value, field))
    )


def _ordered_rules(value, field):
    if not isinstance(value, list):
        raise ValueError(f"{field.capitalize()} must be an ordered list.")
    if len(value) > MAX_RULES:
        raise ValueError(f"Use at most {MAX_RULES} {field}.")
    for rule in value:
        if not isinstance(rule, dict):
            raise ValueError(f"Each {field[:-1]} must be an object.")
    return value


def _rule_id(rule, prefix, index, seen):
    rule_id = str(rule.get("id") or f"{prefix}-{index}")[:120]
    if rule_id in seen:
        raise ValueError("Rule IDs must be unique.")
    seen.add(rule_id)
    return rule_id


def normalize_category_choices(value):
    """Manual on/off choices per account category; they override the rules."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("Category choices must be a list.")
    choices = {}
    for choice in value:
        if not isinstance(choice, dict):
            raise ValueError("Each category choice must be an object.")
        relation = choice.get("relation")
        if isinstance(relation, bool) or not isinstance(relation, int) or relation < 1:
            raise ValueError("Use an account category ID for each choice.")
        if not isinstance(choice.get("enabled"), bool):
            raise ValueError("Each category choice is either enabled or disabled.")
        choices[relation] = choice["enabled"]
    return [
        {"relation": relation, "enabled": enabled}
        for relation, enabled in sorted(choices.items())
    ]


def normalize_excluded_titles(value):
    """Movies and series a profile leaves out, whatever its filters allow."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("Excluded titles must be a list.")
    titles = set()
    for title in value:
        if not isinstance(title, dict) or title.get("content_type") not in (
            "movie",
            "series",
        ):
            raise ValueError("Each excluded title needs a movie or series type.")
        content_id = title.get("id")
        if (
            isinstance(content_id, bool)
            or not isinstance(content_id, int)
            or content_id < 1
        ):
            raise ValueError("Use a Library title ID for each excluded title.")
        titles.add((title["content_type"], content_id))
    return [
        {"content_type": content_type, "id": content_id}
        for content_type, content_id in sorted(titles)
    ]


def normalize_content_filters(value):
    """Hard filters every source must pass before ranking and editions."""
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError("Content filters must be an object.")
    unknown = set(value) - {
        "audio_languages",
        "subtitle_languages",
        "resolution_min",
        "resolution_max",
        "required_features",
        "excluded_features",
        "excluded_genres",
        "adult_mode",
        "anime_mode",
        "missing_tmdb_mode",
    }
    if unknown:
        raise ValueError("Unsupported content filter.")
    filters = {
        "audio_languages": normalize_languages(
            _list(value.get("audio_languages"), "DUB languages")
        ),
        "subtitle_languages": normalize_languages(
            _list(value.get("subtitle_languages"), "SUB languages")
        ),
        "resolution_min": _height(value.get("resolution_min"), "Minimum resolution"),
        "resolution_max": _height(value.get("resolution_max"), "Maximum resolution"),
        "required_features": _features(
            value.get("required_features"), "required features"
        ),
        "excluded_features": _features(
            value.get("excluded_features"), "excluded features"
        ),
        "excluded_genres": list(
            dict.fromkeys(
                _text(term, "genre")
                for term in _list(value.get("excluded_genres"), "excluded genres")
                if str(term or "").strip()
            )
        ),
        "adult_mode": value.get("adult_mode") or "",
        "anime_mode": value.get("anime_mode") or "",
        "missing_tmdb_mode": value.get("missing_tmdb_mode") or "",
    }
    modes = ("adult_mode", "anime_mode", "missing_tmdb_mode")
    if any(filters[mode] not in CONTENT_MODES for mode in modes):
        raise ValueError("Adult, anime and TMDB filters are empty, exclude or only.")
    if (
        filters["resolution_max"]
        and filters["resolution_min"] > filters["resolution_max"]
    ):
        raise FieldError(
            "resolution_max", "Choose a maximum at or above the minimum."
        )
    if set(filters["required_features"]) & set(filters["excluded_features"]):
        raise FieldError(
            "excluded_features", "A feature cannot be required and excluded."
        )
    return {key: item for key, item in filters.items() if item not in ("", [], 0)}


def normalize_edition_rules(value):
    """Ordered first-match editions that split a title into separate entries."""
    rules, seen, suffixes = [], set(), set()
    for index, rule in enumerate(_ordered_rules(value, "editions")):
        try:
            suffix = _text(
                rule.get("title_suffix") or rule.get("name"),
                "an edition suffix",
                required=True,
            )
        except ValueError as error:
            raise FieldError("title_suffix", str(error), index)
        if suffix.casefold() in suffixes:
            raise FieldError(
                "title_suffix", "Use a unique suffix for each edition.", index
            )
        suffixes.add(suffix.casefold())
        normalized = {
            "id": _rule_id(rule, "edition", index, seen),
            "name": _text(rule.get("name") or suffix, "an edition name"),
            "title_suffix": suffix,
            "min_resolution": _height(rule.get("min_resolution"), "Minimum resolution"),
            "max_resolution": _height(rule.get("max_resolution"), "Maximum resolution"),
            "required_audio_languages": normalize_languages(
                _list(rule.get("required_audio_languages"), "DUB languages")
            ),
            "required_subtitle_languages": normalize_languages(
                _list(rule.get("required_subtitle_languages"), "SUB languages")
            ),
            "required_video_features": _features(
                rule.get("required_video_features"), "features"
            ),
        }
        if (
            normalized["max_resolution"]
            and normalized["min_resolution"] > normalized["max_resolution"]
        ):
            raise FieldError(
                "max_resolution", "Choose a maximum at or above the minimum.", index
            )
        if not any(
            normalized[key]
            for key in (
                "min_resolution",
                "max_resolution",
                "required_audio_languages",
                "required_subtitle_languages",
                "required_video_features",
            )
        ):
            raise FieldError(
                "conditions", "Give each edition at least one condition.", index
            )
        rules.append(normalized)
    return rules


def normalize_ranking(value):
    if not isinstance(value, list) or set(value) - set(RANKING_CRITERIA):
        raise ValueError("Use only supported ranking criteria.")
    ranking = list(dict.fromkeys(value))
    if {"resolution_desc", "resolution_asc"} <= set(ranking):
        raise ValueError("Choose one resolution direction.")
    return ranking


def normalize_language_order(value, field):
    return normalize_languages(_list(value, field))


def normalize_provider_order(value):
    accounts = []
    for item in _list(value, "provider order"):
        try:
            account = int(item)
        except (TypeError, ValueError):
            raise ValueError("Use M3U account IDs for the provider order.")
        if account <= 0:
            raise ValueError("Use M3U account IDs for the provider order.")
        if account not in accounts:
            accounts.append(account)
    return accounts


def normalize_name_template(value):
    template = str(value or "").strip()
    if not template or len(template) > 500:
        raise ValueError("Enter an output name format of up to 500 characters.")
    try:
        fields = {
            name
            for _literal, name, _spec, _conversion in string.Formatter().parse(template)
            if name is not None
        }
    except ValueError as error:
        raise ValueError(f"Invalid output name format: {error}")
    if "" in fields or fields - NAME_PLACEHOLDERS:
        unsupported = sorted(field or "{}" for field in fields - NAME_PLACEHOLDERS)
        raise ValueError("Unsupported placeholders: " + ", ".join(unsupported))
    if "title" not in fields:
        raise ValueError("Include {title} in the output name format.")
    return template
