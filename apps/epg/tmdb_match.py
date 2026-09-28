"""Match a programme title to a TMDB TV series or movie."""
from __future__ import annotations

import re
import time
import unicodedata

import requests

TMDB_BASE_URL = 'https://api.themoviedb.org/3'
REQUEST_TIMEOUT = 15

STRONG = 'strong'
LOCALIZED = 'localized'
PARTIAL = 'partial'
_STRENGTH_RANK = {STRONG: 0, LOCALIZED: 1, PARTIAL: 2}

ENGLISH_LANGUAGES = {'en', 'en-GB', 'en-US', 'en-AU', 'en-CA', 'en-IE', 'en-NZ'}

# SD uses ISO 3166-1 alpha-3 country codes, TMDB alpha-2.
ISO3_TO_ISO2 = {
    'ARG': 'AR', 'AUS': 'AU', 'AUT': 'AT', 'BEL': 'BE', 'BRA': 'BR', 'CAN': 'CA', 'CHE': 'CH',
    'CHL': 'CL', 'CHN': 'CN', 'COL': 'CO', 'CZE': 'CZ', 'DEU': 'DE', 'DNK': 'DK', 'ECU': 'EC',
    'ESP': 'ES', 'FIN': 'FI', 'FRA': 'FR', 'GBR': 'GB', 'GRC': 'GR', 'HKG': 'HK', 'HUN': 'HU',
    'IND': 'IN', 'IRL': 'IE', 'ISR': 'IL', 'ITA': 'IT', 'JPN': 'JP', 'KOR': 'KR', 'MEX': 'MX',
    'NLD': 'NL', 'NOR': 'NO', 'NZL': 'NZ', 'PER': 'PE', 'PHL': 'PH', 'POL': 'PL', 'PRT': 'PT',
    'RUS': 'RU', 'SWE': 'SE', 'THA': 'TH', 'TUR': 'TR', 'TWN': 'TW', 'USA': 'US', 'ZAF': 'ZA',
}

_LEADING_ARTICLE_RE = re.compile(r'^(the|a|an|la|el|los|las|le|les|der|die|das)\s+')
_BRACKETED_RE = re.compile(r'\s*[\(\[].*?[\)\]]')
_SUBTITLE_SPLIT_RE = re.compile(r'\s*[:–—]\s+|\s+-\s+')


class TMDBAuthError(Exception):
    """TMDB rejected the API key."""


def normalize_title(title):
    """Lowercase ASCII title without punctuation or a leading article."""
    t = unicodedata.normalize('NFKD', title or '').encode('ascii', 'ignore').decode().lower()
    t = _LEADING_ARTICLE_RE.sub('', t.replace('&', ' and ').strip())
    return re.sub(r'[^a-z0-9]', '', t)


def core_title(title):
    """Normalised title without bracketed text or a trailing subtitle."""
    t = _BRACKETED_RE.sub('', title or '')
    return normalize_title(_SUBTITLE_SPLIT_RE.split(t)[0])


def title_strength(sd_title, tmdb_names, localized):
    """Return STRONG, LOCALIZED, PARTIAL or None for one TMDB result."""
    names = [n for n in tmdb_names if n]
    if any(normalize_title(sd_title) == normalize_title(n) for n in names):
        return LOCALIZED if localized else STRONG
    sd_core = core_title(sd_title)
    if sd_core and any(sd_core == core_title(n) for n in names):
        return PARTIAL
    return None


class TMDBClient:
    """Minimal TMDB v3 client with per-instance response caching."""

    def __init__(self, api_key, session=None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self._cache = {}

    def get(self, path, **params):
        cache_key = (path, tuple(sorted(params.items())))
        if cache_key in self._cache:
            return self._cache[cache_key]
        for attempt in range(3):
            resp = self.session.get(
                f"{TMDB_BASE_URL}{path}",
                params={**params, 'api_key': self.api_key},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 429:
                break
            time.sleep(2 ** (attempt + 1))
        if resp.status_code == 401:
            raise TMDBAuthError()
        resp.raise_for_status()
        data = resp.json()
        self._cache[cache_key] = data
        return data


def _search(client, kind, title, language):
    name_keys = ('name', 'original_name') if kind == 'tv' else ('title', 'original_title')
    queries = [title]
    if core_title(title) != normalize_title(title):
        queries.append(_SUBTITLE_SPLIT_RE.split(_BRACKETED_RE.sub('', title))[0].strip())
    languages = [None]
    if language and language not in ENGLISH_LANGUAGES:
        languages.append(language)

    found = {}
    for query in queries:
        for lang in languages:
            params = {'query': query}
            if lang:
                params['language'] = lang
            for result in client.get(f'/search/{kind}', **params).get('results') or []:
                strength = title_strength(title, [result.get(k) for k in name_keys], bool(lang))
                if not strength:
                    continue
                prev = found.get(result['id'])
                if not prev or _STRENGTH_RANK[strength] < _STRENGTH_RANK[prev[1]]:
                    found[result['id']] = (result, strength)
    return list(found.values())


def _year_fits(kind, result, year):
    date = result.get('first_air_date' if kind == 'tv' else 'release_date') or ''
    tmdb_year = int(date[:4]) if date[:4].isdigit() else None
    if kind == 'tv':
        # SD only exposes episode air dates, so its earliest year bounds the premiere from above.
        return not (year and tmdb_year and tmdb_year > year)
    return bool(year and tmdb_year and abs(tmdb_year - year) <= 1)


def _details(client, kind, tmdb_id):
    if kind == 'tv':
        data = client.get(f'/tv/{tmdb_id}', append_to_response='aggregate_credits,external_ids')
        cast = (data.get('aggregate_credits') or {}).get('cast') or []
        countries = set(data.get('origin_country') or [])
    else:
        data = client.get(f'/movie/{tmdb_id}', append_to_response='credits,external_ids')
        cast = (data.get('credits') or {}).get('cast') or []
        countries = {c.get('iso_3166_1') for c in data.get('production_countries') or []}
        countries |= set(data.get('origin_country') or [])
    return data, {normalize_title(a.get('name')) for a in cast[:40]}, countries


def match_tmdb(client, kind, title, *, language=None, countries=(), year=None, cast=()):
    """Return (TMDB details dict or None, reason).

    ``kind`` is 'tv' or 'movie'. For 'tv', ``year`` is the earliest known air
    year; for 'movie', the release year.
    """
    candidates = [(r, s) for r, s in _search(client, kind, title, language) if _year_fits(kind, r, year)]
    if not candidates:
        return None, 'no title/year match'

    sd_countries = {ISO3_TO_ISO2.get(c, c) for c in countries}
    sd_cast = {normalize_title(n) for n in cast if n}
    scored = []
    for result, strength in candidates:
        details, tmdb_cast, tmdb_countries = _details(client, kind, result['id'])
        cast_hits = len(sd_cast & tmdb_cast)
        country_hit = bool(sd_countries & tmdb_countries)
        if cast_hits or (country_hit and strength != PARTIAL):
            scored.append({'details': details, 'strength': strength, 'cast': cast_hits, 'country': country_hit})
    if not scored:
        return None, 'unconfirmed'

    if any(x['strength'] == STRONG for x in scored):
        scored = [x for x in scored if x['strength'] == STRONG]
    if len(scored) == 1:
        return scored[0]['details'], 'match'
    best_cast = max(x['cast'] for x in scored)
    top = [x for x in scored if x['cast'] == best_cast]
    if best_cast and len(top) == 1:
        return top[0]['details'], 'match (cast tiebreak)'
    by_country = [x for x in scored if x['country']]
    if len(by_country) == 1:
        return by_country[0]['details'], 'match (country tiebreak)'
    return None, 'ambiguous'
