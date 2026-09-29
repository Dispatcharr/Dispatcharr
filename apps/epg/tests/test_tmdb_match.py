"""Tests for TMDB title matching."""
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from apps.epg.tmdb_match import (
    LOCALIZED,
    PARTIAL,
    STRONG,
    TMDBAuthError,
    TMDBClient,
    core_title,
    match_tmdb,
    normalize_title,
    title_strength,
)


class FakeClient:
    """Serves canned TMDB responses: searches keyed by (kind, query, language), details by id."""

    def __init__(self, searches=None, details=None):
        self.searches = searches or {}
        self.details = details or {}
        self.calls = []

    def get(self, path, **params):
        self.calls.append((path, params))
        if path.startswith('/search/'):
            key = (path.split('/')[2], params['query'], params.get('language'))
            return {'results': self.searches.get(key, [])}
        return self.details[int(path.rsplit('/', 1)[1])]


def tv(tmdb_id, name, first_air_date, countries=(), cast=(), original_name=None):
    result = {'id': tmdb_id, 'name': name, 'original_name': original_name or name,
              'first_air_date': first_air_date}
    detail = {**result, 'origin_country': list(countries),
              'aggregate_credits': {'cast': [{'name': n} for n in cast]},
              'external_ids': {'imdb_id': f'tt{tmdb_id}', 'tvdb_id': tmdb_id + 1}}
    return result, detail


def movie(tmdb_id, title, release_date, countries=(), cast=(), original_title=None):
    result = {'id': tmdb_id, 'title': title, 'original_title': original_title or title,
              'release_date': release_date}
    detail = {**result, 'production_countries': [{'iso_3166_1': c} for c in countries],
              'credits': {'cast': [{'name': n} for n in cast]},
              'external_ids': {'imdb_id': f'tt{tmdb_id}'}}
    return result, detail


def client_for(kind, *entries, query, language=None, extra_searches=None):
    searches = {(kind, query, language): [r for r, _ in entries]}
    searches.update(extra_searches or {})
    return FakeClient(searches, {d['id']: d for _, d in entries})


class TitleNormalisationTests(SimpleTestCase):
    def test_normalize(self):
        self.assertEqual(normalize_title('The Cruise: Fun-Loving Brits at Sea'), 'cruisefunlovingbritsatsea')
        self.assertEqual(normalize_title('Águila Roja'), 'aguilaroja')
        self.assertEqual(normalize_title('Russell Howard & Mum'), 'russellhowardandmum')
        self.assertEqual(normalize_title('Der Bergdoktor'), 'bergdoktor')

    def test_core_drops_brackets_and_subtitles(self):
        self.assertEqual(core_title('Dubhlain DIY (Instructions Not Included)'), 'dubhlaindiy')
        self.assertEqual(core_title('Below Deck Down Under: After Show'), 'belowdeckdownunder')
        self.assertEqual(core_title('Terra X - Rätsel alter Weltkulturen'), 'terrax')

    def test_strength(self):
        self.assertEqual(title_strength('Euphoria', ['Euphoria'], False), STRONG)
        self.assertEqual(title_strength('La patrulla canina', ['La patrulla canina'], True), LOCALIZED)
        self.assertEqual(title_strength('BBC News', ['BBC News: 8pm Summary'], False), PARTIAL)
        self.assertIsNone(title_strength('Encuentros', ['Encuentros inesperados'], False))


class MatchTvTests(SimpleTestCase):
    def test_strong_title_with_country(self):
        client = client_for('tv', tv(7378, 'Eòrpa', '1993-01-01', ['GB']), query='Eòrpa')
        details, reason = match_tmdb(client, 'tv', 'Eòrpa', countries=['GBR'], year=2024)
        self.assertEqual(details['id'], 7378)
        self.assertEqual(reason, 'match')

    def test_strong_title_without_corroboration_is_rejected(self):
        client = client_for('tv', tv(1, 'Cash Trapped', '2016-08-01'), query='Cash Trapped')
        details, reason = match_tmdb(client, 'tv', 'Cash Trapped', countries=['GBR'],
                                     year=2019, cast=['Bradley Walsh'])
        self.assertIsNone(details)
        self.assertEqual(reason, 'unconfirmed')

    def test_premiere_after_sd_air_date_is_rejected(self):
        # Minder: the 2009 remake cannot have aired a 1984 episode.
        client = client_for(
            'tv',
            tv(3469, 'Minder', '1979-10-29', ['GB'], ['George Cole']),
            tv(9999, 'Minder', '2009-02-22', ['GB'], ['Shane Richie']),
            query='Minder',
        )
        details, _ = match_tmdb(client, 'tv', 'Minder', countries=['GBR'], year=1984, cast=['George Cole'])
        self.assertEqual(details['id'], 3469)

    def test_cast_breaks_same_name_tie(self):
        client = client_for(
            'tv',
            tv(40458, 'Der Bergdoktor', '1992-01-01', ['DE'], ['Enzi Fuchs']),
            tv(62957, 'Der Bergdoktor', '2008-02-07', ['AT', 'DE'], ['Hans Sigl', 'Heiko Ruprecht']),
            query='Der Bergdoktor',
        )
        details, reason = match_tmdb(client, 'tv', 'Der Bergdoktor', countries=['DEU', 'AUT'],
                                     year=2025, cast=['Hans Sigl', 'Heiko Ruprecht'])
        self.assertEqual(details['id'], 62957)
        self.assertEqual(reason, 'match (cast tiebreak)')

    def test_uncorroborated_same_name_candidate_dropped(self):
        client = client_for(
            'tv',
            tv(20575, 'A Place in the Sun', '2002-11-27', ['GB']),
            tv(325250, 'A Place in the Sun', '2004-01-01', ['RU']),
            query='A Place in the Sun',
        )
        details, reason = match_tmdb(client, 'tv', 'A Place in the Sun', countries=['GBR'], year=2015)
        self.assertEqual(details['id'], 20575)
        self.assertEqual(reason, 'match')

    def test_country_breaks_equal_cast_tie(self):
        client = client_for(
            'tv',
            tv(1, 'Nostalgia', '2020-01-01', ['US'], ['Pierfrancesco Favino']),
            tv(2, 'Nostalgia', '2021-01-01', ['IT'], ['Pierfrancesco Favino']),
            query='Nostalgia',
        )
        details, reason = match_tmdb(client, 'tv', 'Nostalgia', countries=['ITA'], year=2022,
                                     cast=['Pierfrancesco Favino'])
        self.assertEqual(details['id'], 2)
        self.assertEqual(reason, 'match (country tiebreak)')

    def test_unresolvable_tie_is_rejected(self):
        client = client_for(
            'tv',
            tv(1, 'Wheel of Fortune', '1983-01-01', ['GB']),
            tv(2, 'Wheel of Fortune', '1988-01-01', ['GB']),
            query='Wheel of Fortune',
        )
        details, reason = match_tmdb(client, 'tv', 'Wheel of Fortune', countries=['GBR'], year=2024)
        self.assertIsNone(details)
        self.assertEqual(reason, 'ambiguous')

    def test_strong_match_beats_partial_with_more_cast(self):
        # "Below Deck Down Under: After Show" shares cast with the main show.
        client = client_for(
            'tv',
            tv(125506, 'Below Deck Down Under', '2022-03-17', ['US'], ['Jason Chambers']),
            tv(314085, 'Below Deck Down Under: After Show', '2026-02-02', ['US'],
               ['Jason Chambers', 'Daisy Kelliher', 'Ben Robinson']),
            query='Below Deck Down Under',
        )
        details, _ = match_tmdb(client, 'tv', 'Below Deck Down Under', countries=['USA'], year=2026,
                                cast=['Jason Chambers', 'Daisy Kelliher', 'Ben Robinson'])
        self.assertEqual(details['id'], 125506)

    def test_partial_title_needs_cast(self):
        client = client_for(
            'tv', tv(21715, 'BBC News: 8pm Summary', '', ['GB']), query='BBC News',
        )
        details, reason = match_tmdb(client, 'tv', 'BBC News', countries=['GBR'], year=2008)
        self.assertIsNone(details)
        self.assertEqual(reason, 'unconfirmed')

    def test_partial_title_with_cast(self):
        result, detail = tv(290978, 'Instructions Not Included', '2024-05-06', ['GB'], ['Derek Murray'],
                            original_name='Dùbhlain DIY')
        title = 'Dubhlain DIY (Instructions Not Included)'
        client = FakeClient(
            {('tv', 'Dubhlain DIY', None): [result]},
            {290978: detail},
        )
        details, _ = match_tmdb(client, 'tv', title, countries=['GBR'], year=2026, cast=['Derek Murray'])
        self.assertEqual(details['id'], 290978)

    def test_localized_title_search(self):
        localized, detail = tv(57532, 'La patrulla canina', '2013-08-12', ['US'], ['Kallan Holley'],
                               original_name='PAW Patrol')
        client = FakeClient(
            {('tv', 'La patrulla canina', 'es-ES'): [localized]},
            {57532: detail},
        )
        details, _ = match_tmdb(client, 'tv', 'La patrulla canina', language='es-ES',
                                countries=['CAN', 'USA'], year=2013, cast=['Kallan Holley'])
        self.assertEqual(details['id'], 57532)
        searched_languages = {p.get('language') for path, p in client.calls if path == '/search/tv'}
        self.assertEqual(searched_languages, {None, 'es-ES'})

    def test_english_title_language_skips_localized_search(self):
        client = client_for('tv', tv(1, 'Euphoria', '2019-06-16', ['US']), query='Euphoria')
        match_tmdb(client, 'tv', 'Euphoria', language='en-GB', countries=['USA'], year=2026)
        self.assertEqual(
            [p.get('language') for path, p in client.calls if path == '/search/tv'], [None],
        )


class MatchMovieTests(SimpleTestCase):
    def test_year_within_one(self):
        client = client_for('movie', movie(289, 'Casablanca', '1943-01-15', ['US'], ['Humphrey Bogart']),
                            query='Casablanca')
        details, _ = match_tmdb(client, 'movie', 'Casablanca', countries=['USA'], year=1942,
                                cast=['Humphrey Bogart'])
        self.assertEqual(details['id'], 289)

    def test_year_outside_window_rejected(self):
        client = client_for('movie', movie(1, 'Ben-Hur', '1959-11-18', ['US'], ['Charlton Heston']),
                            query='Ben-Hur')
        details, reason = match_tmdb(client, 'movie', 'Ben-Hur', countries=['USA'], year=2016,
                                     cast=['Jack Huston'])
        self.assertIsNone(details)
        self.assertEqual(reason, 'no title/year match')

    def test_missing_year_rejected(self):
        client = client_for('movie', movie(1, 'Primal', '2019-01-01', ['US']), query='Primal')
        details, _ = match_tmdb(client, 'movie', 'Primal', countries=['USA'], year=None)
        self.assertIsNone(details)

    def test_same_title_and_year_without_cast_or_country_rejected(self):
        # SD "Gold" (2022, India) vs TMDB "Gold" (2022, Zac Efron).
        client = client_for('movie', movie(760926, 'Gold', '2022-01-13', ['AU', 'US'], ['Zac Efron']),
                            query='Gold')
        details, reason = match_tmdb(client, 'movie', 'Gold', countries=['IND'], year=2022,
                                     cast=['Prithviraj Sukumaran', 'Nayanthara'])
        self.assertIsNone(details)
        self.assertEqual(reason, 'unconfirmed')


class TMDBClientTests(SimpleTestCase):
    def _resp(self, status, payload=None):
        resp = MagicMock(status_code=status)
        resp.json.return_value = payload or {}
        return resp

    def test_caches_responses_and_sends_key(self):
        session = MagicMock()
        session.get.return_value = self._resp(200, {'results': []})
        client = TMDBClient('k', session=session)
        client.get('/search/tv', query='x')
        client.get('/search/tv', query='x')
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(session.get.call_args.kwargs['params'], {'query': 'x', 'api_key': 'k'})

    def test_unauthorized_raises(self):
        session = MagicMock()
        session.get.return_value = self._resp(401)
        with self.assertRaises(TMDBAuthError):
            TMDBClient('bad', session=session).get('/search/tv', query='x')
