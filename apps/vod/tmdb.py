"""Small, testable TMDB client and canonical metadata normalizers."""

from __future__ import annotations

import re
import time
import unicodedata
from datetime import datetime, timezone

import requests


TMDB_API_ROOT = "https://api.themoviedb.org/3"
TMDB_IMAGE_ROOT = "https://image.tmdb.org/t/p"
TMDB_METADATA_SCHEMA = 5


class TMDBError(RuntimeError):
    pass


class TMDBNotFound(TMDBError):
    pass


class TMDBAuthenticationError(TMDBError):
    pass


def normalize_languages(values):
    languages = []
    for raw in values or []:
        value = str(raw or "").strip()
        match = re.fullmatch(r"([A-Za-z]{2})(?:-([A-Za-z]{2}))?", value)
        if not match:
            continue
        normalized = match.group(1).lower()
        if match.group(2):
            normalized += f"-{match.group(2).upper()}"
        if normalized not in languages:
            languages.append(normalized)
        if len(languages) == 2:
            break
    return languages or ["en-US"]


def normalize_title_rules(values):
    """Normalize ordered literal prefixes removed from VOD titles.

    Older releases stored a match type or a regex ``pattern``.  Reading the
    old value remains supported, but every rule is deliberately interpreted as
    a literal prefix.  Cleanup must never make hidden regex guesses about a
    provider title.
    """
    if not isinstance(values, list):
        raise ValueError("Title rules must be a list")
    rules = []
    for index, raw in enumerate(values[:20]):
        if isinstance(raw, str):
            value = raw.strip()
            enabled = True
        elif isinstance(raw, dict):
            value = str(
                raw.get("value")
                if raw.get("value") is not None
                else raw.get("pattern") or ""
            ).strip()
            enabled = raw.get("enabled") is not False
        else:
            raise ValueError(f"Title prefix {index + 1} must be text")
        action = "remove"
        replacement = ""
        if not value:
            raise ValueError(f"Title prefix {index + 1} cannot be empty")
        if len(value) > 255:
            raise ValueError(f"Title prefix {index + 1} is too long")
        rules.append(
            {
                "match_type": "starts_with",
                "value": value,
                "action": action,
                "replacement": replacement,
                "enabled": enabled,
            }
        )
    return rules


def clean_lookup_title(name, *, display_name="", year=None, rules=None):
    """Create the non-persistent title used for TMDB search and its preview.

    Provider names remain untouched. Only the administrator's ordered
    replacements may remove provider prefixes or otherwise rewrite the title.
    A trailing release year is removed because TMDB receives it in a dedicated
    parameter.
    """
    result = str(display_name or name or "").strip()
    for rule in normalize_title_rules(rules or []):
        if not rule["enabled"]:
            continue
        value = rule["value"]
        if result.startswith(value):
            result = result[len(value):].lstrip()
    if year:
        result = re.sub(
            rf"\s*[\(\[]\s*{re.escape(str(year))}\s*[\)\]]\s*$",
            "",
            result,
        )
    else:
        result = re.sub(r"\s*[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]\s*$", "", result)
    return re.sub(r"\s+", " ", result).strip()


def _normalized_title(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _year(value):
    match = re.match(r"(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def _translation_for_language(translations, language):
    language_code, _, country_code = language.partition("-")
    exact = None
    language_only = None
    for row in translations or []:
        if row.get("iso_639_1") != language_code:
            continue
        if language_only is None:
            language_only = row
        if country_code and row.get("iso_3166_1") == country_code:
            exact = row
            break
    return exact or language_only or {}


def _localized_values(payload, media_type, languages):
    translations = (payload.get("translations") or {}).get("translations") or []
    values = {}
    title_key = "title" if media_type == "movie" else "name"
    original_title_key = (
        "original_title" if media_type == "movie" else "original_name"
    )
    original_language = str(payload.get("original_language") or "").lower()
    for language in languages:
        row = _translation_for_language(translations, language)
        data = row.get("data") if isinstance(row, dict) else {}
        data = data if isinstance(data, dict) else {}
        title = data.get(title_key)
        overview = data.get("overview")
        tagline = data.get("tagline")
        # The details response itself is already localized to the first
        # requested language and is a useful fallback when TMDB omits an
        # explicit translation row.
        if language == languages[0]:
            title = title or payload.get(title_key)
            overview = overview or payload.get("overview")
            tagline = tagline or payload.get("tagline")
        # TMDB often supplies an overview/tagline translation while leaving
        # its translated title empty. If this language is the title's original
        # language, the explicit original title is the authoritative fallback.
        if not title and language.split("-", 1)[0].lower() == original_language:
            title = payload.get(original_title_key) or payload.get(title_key)
        values[language] = {
            "title": str(title or "").strip(),
            "overview": str(overview or "").strip(),
            "tagline": str(tagline or "").strip(),
        }
    return values


def _provider_rows(payload, regions=None):
    provider_payload = (
        payload.get("watch/providers")
        or payload.get("watch_providers")
        or {}
    )
    results = provider_payload.get("results") or {}
    regions = {str(region).upper() for region in regions or [] if region}
    normalized = {}
    for region, region_data in results.items():
        if regions and str(region).upper() not in regions:
            continue
        if not isinstance(region_data, dict):
            continue
        row = {"link": region_data.get("link") or ""}
        for access_type in ("flatrate", "free", "ads", "rent", "buy"):
            providers = []
            for provider in region_data.get(access_type) or []:
                providers.append(
                    {
                        "id": provider.get("provider_id"),
                        "name": provider.get("provider_name") or "",
                        "logo_path": provider.get("logo_path") or "",
                        "priority": provider.get("display_priority"),
                    }
                )
            if providers:
                row[access_type] = providers
        normalized[str(region).upper()] = row
    return normalized


def image_url(path, size):
    path = str(path or "").strip()
    return f"{TMDB_IMAGE_ROOT}/{size}/{path.lstrip('/')}" if path else ""


def _person_names(rows, *, limit=20):
    names = []
    for row in rows or []:
        name = str((row or {}).get("name") or "").strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _director_names(payload, media_type):
    if media_type == "tv":
        creators = _person_names(payload.get("created_by") or [], limit=10)
        if creators:
            return creators
    crew = (payload.get("credits") or {}).get("crew") or []
    return _person_names(
        [row for row in crew if str(row.get("job") or "").lower() == "director"],
        limit=10,
    )


def _crew_labels(payload, *, limit=20):
    labels = []
    for row in (payload.get("credits") or {}).get("crew") or []:
        name = str(row.get("name") or "").strip()
        job = str(row.get("job") or row.get("department") or "").strip()
        if not name or job.lower() == "director":
            continue
        label = f"{name} ({job})" if job else name
        if label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _youtube_trailer(payload):
    videos = (payload.get("videos") or {}).get("results") or []
    candidates = [
        row
        for row in videos
        if row.get("site") == "YouTube"
        and row.get("key")
        and row.get("type") in {"Trailer", "Teaser"}
    ]
    candidates.sort(
        key=lambda row: (
            row.get("type") != "Trailer",
            not bool(row.get("official")),
            -(int(row.get("size") or 0)),
        )
    )
    return str(candidates[0].get("key") or "") if candidates else ""


def _keywords(payload):
    keyword_payload = payload.get("keywords") or {}
    rows = keyword_payload.get("keywords") or keyword_payload.get("results") or []
    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        normalized.append({"id": row.get("id"), "name": name})
    return normalized


def _age_rating(payload, media_type, languages):
    regions = [
        language.partition("-")[2].upper()
        for language in languages
        if language.partition("-")[2]
    ]
    if media_type == "movie":
        rows = (payload.get("release_dates") or {}).get("results") or []
        for region in regions:
            entry = next(
                (row for row in rows if row.get("iso_3166_1") == region), None
            )
            if not entry:
                continue
            releases = entry.get("release_dates") or []
            releases.sort(key=lambda row: row.get("type") != 3)
            for release in releases:
                certification = str(release.get("certification") or "").strip()
                if certification:
                    return certification
    else:
        rows = (payload.get("content_ratings") or {}).get("results") or []
        for region in regions:
            entry = next(
                (row for row in rows if row.get("iso_3166_1") == region), None
            )
            rating = str((entry or {}).get("rating") or "").strip()
            if rating:
                return rating
    return ""


def normalize_details(payload, media_type, languages, *, match_method):
    title_key = "title" if media_type == "movie" else "name"
    date_key = "release_date" if media_type == "movie" else "first_air_date"
    external_ids = payload.get("external_ids") or {}
    normalized_external_ids = {
        key: str(value or "").strip()
        for key, value in {
            "imdb_id": payload.get("imdb_id") or external_ids.get("imdb_id"),
            "tvdb_id": external_ids.get("tvdb_id"),
            "wikidata_id": external_ids.get("wikidata_id"),
        }.items()
        if value not in (None, "")
    }
    poster_path = payload.get("poster_path") or ""
    backdrop_path = payload.get("backdrop_path") or ""
    director_names = _director_names(payload, media_type)
    actor_names = _person_names(
        (payload.get("credits") or {}).get("cast") or [], limit=20
    )
    crew_labels = _crew_labels(payload, limit=20)
    countries = _person_names(payload.get("production_countries") or [], limit=20)
    if not countries:
        countries = [
            str(country or "").strip()
            for country in payload.get("origin_country") or []
            if str(country or "").strip()
        ]
    keywords = _keywords(payload)
    return {
        "schema": TMDB_METADATA_SCHEMA,
        "id": str(payload.get("id") or ""),
        "media_type": media_type,
        "match_method": match_method,
        "original_language": str(payload.get("original_language") or "").strip(),
        "localized": _localized_values(payload, media_type, languages),
        "release_date": str(payload.get(date_key) or ""),
        "release_status": str(payload.get("status") or ""),
        "overview": str(payload.get("overview") or ""),
        "tagline": str(payload.get("tagline") or ""),
        "runtime_minutes": payload.get("runtime") or (
            (payload.get("episode_run_time") or [None])[0]
        ),
        "rating": payload.get("vote_average"),
        "vote_count": payload.get("vote_count"),
        "popularity": payload.get("popularity"),
        "adult": bool(payload.get("adult", False)),
        "age_rating": _age_rating(payload, media_type, languages),
        "director": ", ".join(director_names),
        "actors": ", ".join(actor_names),
        "crew": ", ".join(crew_labels),
        "countries": countries,
        "country": ", ".join(countries),
        "youtube_trailer": _youtube_trailer(payload),
        "keywords": keywords,
        "is_anime": any(
            row["name"].strip().casefold() == "anime" for row in keywords
        ),
        "genres": [
            {"id": row.get("id"), "name": row.get("name") or ""}
            for row in payload.get("genres") or []
        ],
        "networks": [
            {
                "id": row.get("id"),
                "name": row.get("name") or "",
                "logo_path": row.get("logo_path") or "",
                "origin_country": row.get("origin_country") or "",
            }
            for row in payload.get("networks") or []
        ],
        "production_companies": [
            {
                "id": row.get("id"),
                "name": row.get("name") or "",
                "logo_path": row.get("logo_path") or "",
                "origin_country": row.get("origin_country") or "",
            }
            for row in payload.get("production_companies") or []
        ],
        "watch_providers": _provider_rows(
            payload,
            [language.partition("-")[2] for language in languages],
        ),
        "poster_path": poster_path,
        "poster_url": image_url(poster_path, "w500"),
        "backdrop_path": backdrop_path,
        "backdrop_url": image_url(backdrop_path, "w1280"),
        "external_ids": normalized_external_ids,
        "imdb_id": normalized_external_ids.get("imdb_id", ""),
        "tvdb_id": normalized_external_ids.get("tvdb_id", ""),
        "wikidata_id": normalized_external_ids.get("wikidata_id", ""),
        "homepage": str(payload.get("homepage") or ""),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def preferred_title(metadata, language=None):
    """Resolve a localized title without ever falling back to provider data."""
    metadata = metadata if isinstance(metadata, dict) else {}
    localized = metadata.get("localized") or {}
    if language:
        title = (localized.get(language) or {}).get("title")
        if title:
            return str(title).strip()
    for values in localized.values():
        title = values.get("title") if isinstance(values, dict) else ""
        if title:
            return str(title).strip()
    return ""


def canonical_fields_from_metadata(
    metadata,
    language,
    media_type,
):
    metadata = metadata if isinstance(metadata, dict) else {}
    overrides = metadata.get("_manual_overrides") or {}
    localized = metadata.get("localized") or {}
    localized_overrides = overrides.get("localized") or {}
    primary = localized.get(language) or {}
    primary_overrides = localized_overrides.get(language) or {}
    update = {}

    title = preferred_title(metadata, language)
    if title:
        update["display_name"] = title[:255]
        update["clean_title"] = title[:255]

    description = primary.get("overview") or metadata.get("overview") or ""
    if description or "overview" in primary_overrides or "overview" in overrides:
        update["description"] = str(description)

    release_date = str(metadata.get("release_date") or "")
    year_match = re.match(r"(\d{4})", release_date)
    if year_match:
        update["year"] = int(year_match.group(1))
    elif "release_date" in overrides:
        update["year"] = None

    if metadata.get("rating") not in (None, "") or "rating" in overrides:
        update["rating"] = str(metadata.get("rating") or "")

    genres = metadata.get("genres") or []
    if genres or "genres" in overrides:
        update["genre"] = ", ".join(
            str(row.get("name") or "").strip()
            for row in genres
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        )[:255]

    if media_type == "movie":
        runtime = metadata.get("runtime_minutes")
        if runtime not in (None, ""):
            try:
                update["duration_secs"] = int(float(runtime) * 60)
            except (TypeError, ValueError):
                pass
        elif "runtime_minutes" in overrides:
            update["duration_secs"] = None

    return update


def apply_manual_overrides(metadata, overrides):
    """Overlay administrator-owned values onto a normalized TMDB document.

    Empty strings are intentional here: an administrator can also clear a
    value. The compact override document is retained so a later TMDB refresh
    can fetch fresh upstream data without losing local edits.
    """
    metadata = dict(metadata or {})
    overrides = dict(overrides or {})
    overrides.pop("id", None)
    for key, value in overrides.items():
        if key in {"localized", "external_ids"}:
            current = dict(metadata.get(key) or {})
            if key == "localized":
                for language, localized_values in (value or {}).items():
                    current[language] = {
                        **dict(current.get(language) or {}),
                        **dict(localized_values or {}),
                    }
            else:
                current.update(dict(value or {}))
            metadata[key] = current
        else:
            metadata[key] = value
    if overrides:
        metadata["_manual_overrides"] = overrides
    else:
        metadata.pop("_manual_overrides", None)
    return metadata


class Client:
    def __init__(self, token, *, session=None, min_interval=0.04, timeout=15):
        self.token = str(token or "").strip()
        if not self.token:
            raise ValueError("A TMDB API token is required")
        self.session = session or requests.Session()
        self.min_interval = max(float(min_interval), 0)
        self.timeout = timeout
        self._last_request_at = 0.0

    def _auth(self):
        # TMDB v4 read tokens are long/JWT-like; v3 keys remain supported for
        # existing installations.
        if len(self.token) > 64 or self.token.count(".") == 2:
            return {"Authorization": f"Bearer {self.token}"}, {}
        return {}, {"api_key": self.token}

    def get(self, path, **params):
        headers, auth_params = self._auth()
        params = {**auth_params, **params}
        for attempt in range(4):
            delay = self.min_interval - (time.monotonic() - self._last_request_at)
            if delay > 0:
                time.sleep(delay)
            try:
                response = self.session.get(
                    f"{TMDB_API_ROOT}/{path.lstrip('/')}",
                    headers={"Accept": "application/json", **headers},
                    params=params,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise TMDBError(str(exc)) from exc
            self._last_request_at = time.monotonic()
            if response.status_code == 404:
                raise TMDBNotFound(path)
            if response.status_code in {401, 403}:
                raise TMDBAuthenticationError(
                    "TMDB rejected the configured API token"
                )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 3:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        retry_after = float(retry_after)
                    except (TypeError, ValueError):
                        retry_after = 0.5 * (attempt + 1)
                    time.sleep(min(max(retry_after, 0.1), 10))
                    continue
            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                raise TMDBError(str(exc)) from exc
            try:
                payload = response.json()
            except ValueError as exc:
                raise TMDBError("TMDB returned invalid JSON") from exc
            if not isinstance(payload, dict):
                raise TMDBError("TMDB returned a non-object response")
            return payload
        raise TMDBError("TMDB request retries exhausted")

    def find_by_imdb(self, imdb_id, media_type):
        payload = self.get(
            f"find/{imdb_id}",
            external_source="imdb_id",
        )
        key = "movie_results" if media_type == "movie" else "tv_results"
        rows = payload.get(key) or []
        return str(rows[0].get("id")) if len(rows) == 1 and rows[0].get("id") else ""

    def search(self, query, year, media_type, language):
        match_id, _status, _count = self.search_outcome(
            query, year, media_type, language
        )
        return match_id

    def search_outcome(self, query, year, media_type, language):
        """Return an exact match plus a visible zero/ambiguous outcome."""
        rows = self.search_candidates(query, year, media_type, language)
        title_keys = ("title", "original_title")
        wanted = _normalized_title(query)
        candidates = []
        for row in rows:
            names = {_normalized_title(row.get(key)) for key in title_keys}
            if wanted not in names:
                continue
            candidate_year = row.get("year")
            if year and candidate_year and abs(int(year) - int(candidate_year)) > 1:
                continue
            candidates.append(row)
        if not candidates:
            return "", "not_found", 0
        if len(candidates) > 1:
            return "", "ambiguous", len(candidates)
        return str(candidates[0].get("id") or ""), "matched", 1

    def search_candidates(self, query, year, media_type, language):
        params = {
            "query": query,
            "language": language,
            "include_adult": "true",
        }
        if year:
            params[
                "primary_release_year" if media_type == "movie" else "first_air_date_year"
            ] = year
        payload = self.get(f"search/{'movie' if media_type == 'movie' else 'tv'}", **params)
        title_key = "title" if media_type == "movie" else "name"
        original_title_key = (
            "original_title" if media_type == "movie" else "original_name"
        )
        date_key = "release_date" if media_type == "movie" else "first_air_date"
        candidates = []
        for row in payload.get("results") or []:
            if not row.get("id"):
                continue
            candidates.append(
                {
                    "id": str(row.get("id")),
                    "title": str(row.get(title_key) or "").strip(),
                    "original_title": str(row.get(original_title_key) or "").strip(),
                    "release_date": str(row.get(date_key) or "").strip(),
                    "year": _year(row.get(date_key)),
                    "overview": str(row.get("overview") or "").strip(),
                    "poster_url": image_url(row.get("poster_path"), "w185"),
                    "backdrop_url": image_url(row.get("backdrop_path"), "w780"),
                    "rating": row.get("vote_average"),
                    "popularity": row.get("popularity"),
                    "original_language": str(
                        row.get("original_language") or ""
                    ).strip(),
                    "adult": bool(row.get("adult", False)),
                }
            )
        return candidates

    def details(self, tmdb_id, media_type, languages, *, match_method):
        languages = normalize_languages(languages)
        media_path = "movie" if media_type == "movie" else "tv"
        appended = [
            "translations",
            "external_ids",
            "watch/providers",
            "credits",
            "videos",
            "keywords",
            "release_dates" if media_type == "movie" else "content_ratings",
        ]
        payload = self.get(
            f"{media_path}/{tmdb_id}",
            language=languages[0],
            append_to_response=",".join(appended),
        )
        return normalize_details(
            payload,
            media_type,
            languages,
            match_method=match_method,
        )
