"""Operator-assigned language/quality on ``M3UVODCategoryRelation.custom_properties``."""
import re

QUALITY_ORDER = ("4K", "1080p", "720p", "480p", "SD")

_LANGUAGE_CODE_RE = re.compile(r"[A-Za-z]{2}")


def validate_category_custom_properties(props):
    """Return a copy of ``props`` with ``language`` lowercased.

    Raises ``ValueError`` with a message safe to return to the API caller.
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


def category_language(category_relation):
    """Identity language for content ingested under this category relation (``''`` when untagged)."""
    if category_relation is None:
        return ''
    props = category_relation.custom_properties or {}
    language = props.get("language")
    return language.lower() if isinstance(language, str) else ''
