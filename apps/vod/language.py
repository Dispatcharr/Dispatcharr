"""VOD category language & quality resolution.

Language is never inferred from a title. The only two sources are the
operator's manual category assignment (``M3UVODCategoryRelation.custom_properties``)
and, where a provider happens to expose it, the provider's own per-stream
language field (``M3UMovieRelation``/``M3UEpisodeRelation``/``M3USeriesRelation``
``custom_properties['language']``). Quality is the only thing that uses title
matching, and only as the first step of its own precedence chain:

    language(relation) = provider-supplied language
                      or category language
                      or None

    quality(relation)  = title match on the item name
                      or category default quality
                      or None
"""
import logging
import re

from django.core.cache import cache

logger = logging.getLogger(__name__)

CATEGORY_META_CACHE_KEY = "vod:category_meta:v1"
CATEGORY_META_CACHE_TTL = None  # cached indefinitely; invalidated explicitly on write

QUALITY_ORDER = ("4K", "1080p", "720p", "480p", "SD")

# Title already ends in a bracketed/parenthesised 2-letter token, e.g. "(EN)" or "[es]".
# Captures the code itself so callers can tell a same-language tag (already
# ours, don't double it) from an unrelated one (e.g. a country-of-origin
# code like "(UK)", which isn't a language tag at all and shouldn't block ours).
SUFFIX_RE = re.compile(r"[\[(]([A-Za-z]{2})[\])]\s*$")

# Priority-ordered, case-sensitive substrings, matching the pre-existing
# get_quality_info name-matching branch exactly (a title can contain more
# than one token; the highest-priority one wins regardless of position).
_QUALITY_NAME_TOKENS = (
    (('4K', '2160p'), '4K'),
    (('1080p', 'FHD'), '1080p'),
    (('720p', 'HD'), '720p'),
    (('480p',), '480p'),
)


def get_category_metadata():
    """Return ``{(m3u_account_id, category_id): {"language": ..., "quality": ...}}``.

    Single query over ``M3UVODCategoryRelation``, cached in Django's cache
    under ``CATEGORY_META_CACHE_KEY`` until explicitly invalidated by
    ``invalidate_category_metadata_cache()`` (called at the end of
    ``update_group_settings``). Resolution is always live against current
    config; nothing is baked into ingested rows.
    """
    cached = cache.get(CATEGORY_META_CACHE_KEY)
    if cached is not None:
        return cached

    from .models import M3UVODCategoryRelation

    meta = {}
    for row in M3UVODCategoryRelation.objects.values(
        "m3u_account_id", "category_id", "custom_properties"
    ):
        props = row["custom_properties"] or {}
        language = props.get("language")
        quality = props.get("quality")
        if not language and not quality:
            continue
        meta[(row["m3u_account_id"], row["category_id"])] = {
            "language": language,
            "quality": quality,
        }

    cache.set(CATEGORY_META_CACHE_KEY, meta, CATEGORY_META_CACHE_TTL)
    return meta


def invalidate_category_metadata_cache():
    cache.delete(CATEGORY_META_CACHE_KEY)


_LANGUAGE_CODE_RE = re.compile(r"[A-Za-z]{2}")


def validate_category_custom_properties(props):
    """Validate/normalise the ``language``/``quality`` keys of a category
    relation's ``custom_properties`` dict.

    Returns a copy of ``props`` with ``language`` lowercased. Raises
    ``ValueError`` (message is safe to surface to the API caller) so both
    the DRF serializer and the raw ``update_group_settings`` write path can
    reject bad input with a 400 instead of silently storing junk. Unknown
    keys are left untouched.
    """
    props = dict(props or {})

    language = props.get("language")
    if language is not None:
        if not isinstance(language, str) or not _LANGUAGE_CODE_RE.fullmatch(language):
            raise ValueError("language must be a 2-letter ISO 639-1 code or null.")
        props["language"] = language.lower()

    quality = props.get("quality")
    if quality is not None and quality not in QUALITY_ORDER:
        raise ValueError(f"quality must be one of {', '.join(QUALITY_ORDER)} or null.")

    return props


def vod_language_enabled():
    """True iff any category relation has a language assigned."""
    return any(meta.get("language") for meta in get_category_metadata().values())


def resolve_language(rel_lang, cat_meta):
    """``rel_lang`` (provider-supplied) wins; else the category's assigned language; else None."""
    if rel_lang:
        return rel_lang
    if cat_meta:
        cat_lang = cat_meta.get("language")
        if cat_lang:
            return cat_lang
    return None


def match_quality_from_name(name):
    """The one place a quality tag is pattern-matched out of a title.

    Shared by ``resolve_quality`` (category-language output ranking) and
    ``M3UMovieRelationSerializer.get_quality_info`` / episode equivalent (the
    pre-existing name-matching branch of quality detection), so there is
    exactly one implementation of the pattern.
    """
    if not name:
        return None
    for tokens, quality in _QUALITY_NAME_TOKENS:
        if any(token in name for token in tokens):
            return quality
    return None


def resolve_quality(name, cat_meta):
    """Title match on ``name`` first, then the category's default quality, else None."""
    matched = match_quality_from_name(name)
    if matched:
        return matched
    if cat_meta:
        cat_quality = cat_meta.get("quality")
        if cat_quality:
            return cat_quality
    return None


# Provider audio metadata commonly reports ISO 639-2/B (3-letter) codes rather
# than the 2-letter ISO 639-1 codes categories are assigned in. Cover the
# common cases so "eng"/"spa" style values still resolve; anything not listed
# here is simply not usable as a provider-supplied language (falls through to
# the category assignment, same as no language at all).
_ISO_639_2_TO_1 = {
    "eng": "en", "spa": "es", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de",
    "ita": "it", "por": "pt", "rus": "ru", "ara": "ar", "chi": "zh", "zho": "zh",
    "jpn": "ja", "kor": "ko", "hin": "hi", "tur": "tr", "pol": "pl", "dut": "nl",
    "nld": "nl", "swe": "sv", "nor": "no", "dan": "da", "fin": "fi", "gre": "el",
    "ell": "el", "heb": "he", "tha": "th", "vie": "vi", "ukr": "uk", "cze": "cs",
    "ces": "cs", "hun": "hu", "rum": "ro", "ron": "ro", "bul": "bg", "srp": "sr",
    "hrv": "hr", "slo": "sk", "slk": "sk", "ind": "id",
}

_LANGUAGE_FIELD_CANDIDATES = ("language", "audio_language", "lang")


def _normalize_language_code(value):
    """A 2-letter ISO 639-1 code, mapping known 3-letter (ISO 639-2) codes, else None."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if len(value) == 2 and value.isalpha():
        return value
    if len(value) == 3:
        return _ISO_639_2_TO_1.get(value)
    return None


def extract_provider_language(data):
    """Pull a provider-supplied language out of a raw provider payload dict.

    Checks the direct fields a provider might use for a single-stream
    language (``language``, ``audio_language``, ``lang``), then the
    language entry inside ``detailed_info.audio``, where present. Returns a
    lowercase 2-letter ISO 639-1 code, or ``None`` if nothing usable was
    found. Language is only ever taken from the provider when it is
    actually present, never guessed.
    """
    if not isinstance(data, dict):
        return None

    for field in _LANGUAGE_FIELD_CANDIDATES:
        code = _normalize_language_code(data.get(field))
        if code:
            return code

    detailed_info = data.get("detailed_info")
    audio_candidates = (
        data.get("audio"),
        detailed_info.get("audio") if isinstance(detailed_info, dict) else None,
    )
    for audio in audio_candidates:
        if not isinstance(audio, dict):
            continue
        for field in _LANGUAGE_FIELD_CANDIDATES:
            code = _normalize_language_code(audio.get(field))
            if code:
                return code

    return None


def resolve_movie_relation(raw_id, extra_filters=None, select_related=('movie',)):
    """Resolve an XC movie `stream_id` path param to an `M3UMovieRelation`.

    Once any category has a language assigned, movie `stream_id` values
    emitted by the API are `M3UMovieRelation.id`, not `Movie.id`. The two
    are separate sequences that can collide numerically, so the value is
    tried as a relation id first, falling back to a `Movie.id` lookup only
    on miss (a client that scanned before the switch, or the feature is
    off and `stream_id` was never anything but `Movie.id`). Logs the
    fallback at debug so operators can see stale clients.
    """
    from .models import M3UMovieRelation

    filters = {"m3u_account__is_active": True, **(extra_filters or {})}

    try:
        relation = (
            M3UMovieRelation.objects.filter(pk=raw_id, **filters)
            .select_related(*select_related)
            .order_by('-m3u_account__priority', 'id')
            .first()
        )
    except (ValueError, TypeError):
        relation = None

    if relation:
        return relation

    logger.debug(
        "VOD relation-id lookup missed for stream_id=%s; falling back to Movie.id",
        raw_id,
    )
    try:
        return (
            M3UMovieRelation.objects.filter(movie_id=raw_id, **filters)
            .select_related(*select_related)
            .order_by('-m3u_account__priority', 'id')
            .first()
        )
    except (ValueError, TypeError):
        return None


def category_id_for_relation(relation):
    """The `VODCategory` id governing `relation`'s language/quality metadata.

    Movie and series relations carry `category` directly. `M3UEpisodeRelation`
    has no `category` field of its own; it inherits one from its parent
    `series_relation`. This function resolves that indirection so callers
    can get a relation's category regardless of content type.
    """
    if hasattr(relation, 'series_relation_id'):
        return relation.series_relation.category_id if relation.series_relation_id else None
    return relation.category_id


def resolve_episode_relation(raw_id, extra_filters=None, select_related=('episode', 'series_relation')):
    """Resolve an XC episode `stream_id` path param to an `M3UEpisodeRelation`.

    Mirrors `resolve_movie_relation`: once any category has a language
    assigned, episode `stream_id` values emitted by the API are
    `M3UEpisodeRelation.id`, not `Episode.id`. The two are separate
    sequences that can collide numerically, so the value is tried as a
    relation id first, falling back to an `Episode.id` lookup only on miss
    (a client that scanned before the switch, or the feature is off and
    `stream_id` was never anything but `Episode.id`).
    """
    from .models import M3UEpisodeRelation

    filters = {"m3u_account__is_active": True, **(extra_filters or {})}

    try:
        relation = (
            M3UEpisodeRelation.objects.filter(pk=raw_id, **filters)
            .select_related(*select_related)
            .order_by('-m3u_account__priority', 'id')
            .first()
        )
    except (ValueError, TypeError):
        relation = None

    if relation:
        return relation

    logger.debug(
        "VOD relation-id lookup missed for stream_id=%s; falling back to Episode.id",
        raw_id,
    )
    try:
        return (
            M3UEpisodeRelation.objects.filter(episode_id=raw_id, **filters)
            .select_related(*select_related)
            .order_by('-m3u_account__priority', 'id')
            .first()
        )
    except (ValueError, TypeError):
        return None


def quality_rank(quality):
    """Sort index for ``quality``; unknown/None sorts last."""
    try:
        return QUALITY_ORDER.index(quality)
    except (ValueError, TypeError):
        return len(QUALITY_ORDER)


def apply_language_suffix(name, lang):
    """Append the resolved language to ``name`` as a visible tag.

    No-op only when ``lang`` is falsy, or when ``name`` already ends in a
    bracketed/parenthesised tag matching ``lang`` itself (case-insensitively);
    that title is already correctly tagged, so nothing is added.

    A different trailing 2-letter token (a country-of-origin code like
    "(UK)", or another language) is not language information about the
    group this relation was assigned to, so it does not suppress the tag.
    It gets " - (XX)" appended alongside it, e.g. "The Apprentice (UK)" in a
    Spanish-assigned category becomes "The Apprentice (UK) - (ES)". A bare
    title with no existing trailing token gets " [XX]" instead.
    """
    if not lang or not name:
        return name
    lang_upper = lang.upper()
    match = SUFFIX_RE.search(name)
    if not match:
        return f"{name} [{lang_upper}]"
    if match.group(1).upper() == lang_upper:
        return name
    return f"{name} - ({lang_upper})"
