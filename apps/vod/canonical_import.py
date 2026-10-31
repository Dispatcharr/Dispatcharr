"""Exact, source-independent title matching for provider imports."""

import re
import unicodedata
from collections import defaultdict

from django.db.models import OuterRef, Subquery
from django.db.models.fields.json import KeyTransform

from .title_cleanup import clean_lookup_title


def title_key(value):
    return (
        re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")))
        .strip()
        .casefold()
    )


def category_cleanup(relation):
    return (
        ((relation.custom_properties or {}).get("title_cleanup") or {})
        if relation
        else {}
    )


class ImportTitleError(ValueError):
    """A cleanup failure must abort an import, not make sources disappear."""


def import_title(name, year, settings, category_relation=None, *, group_rule=None):
    try:
        cleaned = clean_lookup_title(
            name,
            year=year,
            rules=settings["title_rules"],
            year_rules=settings["year_rules"],
            removal_rules=settings.get("removal_rules"),
            group_rule=(
                group_rule
                if group_rule is not None
                else category_cleanup(category_relation)
            ),
        )
    except ValueError as exc:
        raise ImportTitleError(
            "Configured title cleanup could not be applied; import aborted."
        ) from exc
    return (cleaned or name)[:255]


def compatible_identity(candidate, properties):
    for field in ("tmdb_id", "imdb_id"):
        incoming, current = properties.get(field), candidate.get(field)
        if incoming and current and str(incoming) != str(current):
            return False
    return True


class CanonicalImportIndex:
    """Load each release year once per import, not once per provider batch.

    Candidate tiers are primary, translated, cleaned and provider title. A
    collision in a higher tier is ambiguous; lower tiers cannot override it.
    No title-only or fuzzy matching is permitted.
    """

    def __init__(self, model, settings):
        self.model, self.settings = model, settings
        self.years = set()
        self.rows = {}
        self.tiers = [defaultdict(set) for _ in range(4)]
        self.keys = {}

    def _remember(self, row):
        pk = row["id"]
        for tier, key in self.keys.pop(pk, ()):
            self.tiers[tier][key].discard(pk)
        self.rows[pk] = row
        year = row["year"]
        if year is None:
            return
        localized = row.get("localized") or {}
        if not isinstance(localized, dict):
            localized = {}
        cleaned = import_title(
            row["name"],
            year,
            self.settings,
            group_rule=row.get("cleanup") or {},
        )
        titles = (
            [row.get("display_name")],
            [
                value.get("title")
                for value in localized.values()
                if isinstance(value, dict)
            ],
            [row.get("clean_title"), cleaned],
            [row["name"]],
        )
        self.keys[pk] = []
        for tier, values in enumerate(titles):
            for value in values:
                key = (title_key(value), year)
                if key[0]:
                    self.tiers[tier][key].add(pk)
                    self.keys[pk].append((tier, key))

    def load(self, properties):
        from .models import (
            M3UMovieRelation,
            M3USeriesRelation,
            M3UVODCategoryRelation,
            Movie,
        )

        years = {
            row["year"] for row in properties if row.get("year") is not None
        } - self.years
        if not years:
            return
        kind, source_model = (
            ("movie", M3UMovieRelation)
            if self.model is Movie
            else ("series", M3USeriesRelation)
        )
        category = M3UVODCategoryRelation.objects.filter(
            m3u_account_id=OuterRef("m3u_account_id"),
            category_id=OuterRef("category_id"),
        ).values("custom_properties__title_cleanup")[:1]
        source = (
            source_model.objects.filter(**{f"{kind}_id": OuterRef("pk")})
            .order_by("-m3u_account__priority", "m3u_account_id", "pk")
            .annotate(
                cleanup=Subquery(category),
            )
            .values("cleanup")[:1]
        )
        rows = (
            self.model.objects.filter(year__in=years)
            .annotate(
                localized=KeyTransform("localized", "tmdb_metadata"),
                cleanup=Subquery(source),
            )
            .values(
                "id",
                "name",
                "year",
                "clean_title",
                "display_name",
                "tmdb_id",
                "imdb_id",
                "localized",
                "cleanup",
            )
        )
        for row in rows.iterator(chunk_size=1000):
            self._remember(row)
        self.years.update(years)

    def matches(self, properties):
        self.load(properties)
        result = {}
        for props in properties:
            key = (title_key(props.get("clean_title")), props.get("year"))
            if not key[0] or key[1] is None:
                continue
            for tier in self.tiers:
                ids = tier.get(key, set())
                if len(ids) > 1:
                    break
                if ids:
                    pk = next(iter(ids))
                    if compatible_identity(self.rows[pk], props):
                        result[id(props)] = pk
                    break
        return self.model.objects.in_bulk(set(result.values())), result

    def ambiguous(self, key):
        for tier in self.tiers:
            if tier.get(key):
                return len(tier[key]) > 1
        return False

    def remember(self, rows):
        for content in rows:
            self._remember(
                {
                    "id": content.pk,
                    "name": content.name,
                    "year": content.year,
                    "clean_title": content.clean_title,
                    "display_name": content.display_name,
                    "tmdb_id": content.tmdb_id,
                    "imdb_id": content.imdb_id,
                    "localized": (content.tmdb_metadata or {}).get("localized") or {},
                }
            )


def coalesce_title_entries(entries, index, existing_relations, content_field):
    """Coalesce compatible new batch rows, including rows with missing IDs."""
    groups = defaultdict(list)
    index.load([row["props"] for row in entries.values()])
    for key, row in entries.items():
        props = row["props"]
        if key[0] in {"override", "source"} or props.get("year") is None:
            continue
        groups[(title_key(props.get("clean_title")), props["year"])].append(key)
    for group_key, keys in groups.items():
        if len(keys) < 2:
            continue
        if index.ambiguous(group_key):
            continue
        existing = [key for key in keys if key[0] == "existing"]
        if len(existing) > 1:
            continue
        identities = {field: set() for field in ("tmdb_id", "imdb_id")}
        for key in keys:
            data = entries[key]
            for field, values in identities.items():
                incoming = data["props"].get(field)
                if incoming:
                    values.add(str(incoming))
                else:
                    for provider_id in data["occurrences"]:
                        source = existing_relations.get(provider_id)
                        current = getattr(
                            getattr(source, content_field, None), field, None
                        )
                        if current:
                            values.add(str(current))
        if any(len(values) > 1 for values in identities.values()):
            continue
        target_key = next(
            iter(existing),
            next(
                (key for key in keys if key[0] == "tmdb"),
                next((key for key in keys if key[0] == "imdb"), keys[0]),
            ),
        )
        target = entries[target_key]
        for key in keys:
            if key == target_key:
                continue
            source = entries.pop(key)
            for field in ("tmdb_id", "imdb_id"):
                if not target["props"].get(field) and source["props"].get(field):
                    target["props"][field] = source["props"][field]
            target["occurrences"].update(source["occurrences"])
            target["logo_url"] = target.get("logo_url") or source.get("logo_url")
