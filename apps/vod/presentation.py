"""Canonical title precedence shared by the Library and client catalogues."""


def canonical_title(content, languages):
    metadata = content.tmdb_metadata or {}
    localized = metadata.get("localized") or {}
    translations = (
        (localized.get(language) or {}).get("title") for language in languages
    )
    for value in (
        content.display_name,
        *translations,
        content.clean_title,
        content.name,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def canonical_title_expression(prefix, languages):
    """Resolve the same title in SQL, without fetching full metadata per row."""
    from django.db.models import F, TextField, Value
    from django.db.models.fields.json import KeyTextTransform, KeyTransform
    from django.db.models.functions import Coalesce, NullIf, Trim

    localized = KeyTransform("localized", F(f"{prefix}tmdb_metadata"))
    candidates = [
        F(f"{prefix}display_name"),
        *(
            KeyTextTransform("title", KeyTransform(language, localized))
            for language in languages
        ),
        F(f"{prefix}clean_title"),
        F(f"{prefix}name"),
    ]
    return Coalesce(
        *(NullIf(Trim(value), Value("")) for value in candidates),
        Value(""),
        output_field=TextField(),
    )


def profile_overview(content, language, fallback=""):
    """A Library-edited overview, else the overview in a profile's language."""
    metadata = content.tmdb_metadata or {}
    edited = ((metadata.get("_manual_overrides") or {}).get("library") or {}).get(
        "overview"
    )
    translated = ((metadata.get("localized") or {}).get(language) or {}).get(
        "overview"
    )
    for value in (edited, translated):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def profile_overview_expression(prefix, language):
    """Resolve profile_overview in SQL, falling back to the description."""
    from django.db.models import F, TextField, Value
    from django.db.models.fields.json import KeyTextTransform, KeyTransform
    from django.db.models.functions import Coalesce, NullIf, Trim

    metadata = F(f"{prefix}tmdb_metadata")
    edited = KeyTextTransform(
        "overview",
        KeyTransform("library", KeyTransform("_manual_overrides", metadata)),
    )
    translated = KeyTextTransform(
        "overview", KeyTransform(language, KeyTransform("localized", metadata))
    )
    return Coalesce(
        NullIf(Trim(edited), Value("")),
        NullIf(Trim(translated), Value("")),
        F(f"{prefix}description"),
        Value(""),
        output_field=TextField(),
    )


def library_list_annotations(prefix, language):
    """The Library plot, IDs, genres, rating and year for catalogue lists, in SQL.

    Lists stay lean: they read these few keys, not the whole metadata.
    """
    from django.db.models import F, Value
    from django.db.models.fields.json import KeyTextTransform, KeyTransform
    from django.db.models.functions import Coalesce, NullIf

    metadata = F(f"{prefix}tmdb_metadata")
    return {
        "_library_plot": profile_overview_expression(prefix, language),
        "_library_tmdb_id": Coalesce(
            NullIf(F(f"{prefix}tmdb_match_id"), Value("")), F(f"{prefix}tmdb_id")
        ),
        "_library_imdb_id": Coalesce(
            NullIf(F(f"{prefix}tmdb_imdb_id"), Value("")), F(f"{prefix}imdb_id")
        ),
        "_library_genres": KeyTransform("genres", metadata),
        "_library_rating": KeyTextTransform("rating", metadata),
        "_library_release": KeyTextTransform("release_date", metadata),
        "_library_year": KeyTextTransform(
            "year", KeyTransform("_manual_overrides", metadata)
        ),
    }


def library_list_values(row, genre, rating, year):
    """Genre, rating and year from library_list_annotations, as the Library
    document resolves them; the provider values fill the gaps."""
    import re

    genres = row["_library_genres"]
    if isinstance(genres, list):
        genre = ", ".join(
            item["name"]
            for item in genres
            if isinstance(item, dict) and item.get("name")
        )
    release = row["_library_release"] or ""
    if row["_library_year"]:
        year = row["_library_year"]
    elif re.match(r"\d{4}", release):
        year = int(release[:4])
    return genre, row["_library_rating"] or rating, year


def canonical_title_search(prefix, languages, query):
    from django.db.models import Q

    fields = [f"{prefix}{field}" for field in ("name", "clean_title", "display_name")]
    fields.extend(
        f"{prefix}tmdb_metadata__localized__{language}__title" for language in languages
    )
    matching = Q()
    for field in fields:
        matching |= Q(**{f"{field}__icontains": query})
    return matching
