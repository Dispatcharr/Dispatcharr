from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from apps.vod.title_cleanup import (
    clean_lookup_title,
    extract_year_from_title,
    normalize_group_title_cleanup,
    normalize_title_rules,
    normalize_year_rules,
)
from apps.vod.tmdb import (
    Client,
    TMDBAuthenticationError,
    TMDBError,
    normalize_details,
    normalize_language_order,
    normalize_languages,
)


class TitleCleanupTests(SimpleTestCase):
    def test_literal_prefix_spacing_does_not_truncate_a_different_word(self):
        self.assertEqual(clean_lookup_title("DE Film", rules=["DE "]), "Film")
        self.assertEqual(clean_lookup_title("DEAD", rules=["DE "]), "DEAD")
        self.assertEqual(extract_year_from_title("Film (1895)"), 1895)

    def test_cleanup_is_explicit_ordered_and_does_not_guess_prefixes(self):
        title = "4K-AMZ - NF - Film (2021)"
        self.assertEqual(clean_lookup_title(title, year=2021), "4K-AMZ - NF - Film")
        self.assertEqual(
            clean_lookup_title(title, year=2021, rules=["4K-AMZ -", "NF -"]), "Film"
        )
        self.assertEqual(title, "4K-AMZ - NF - Film (2021)")

    def test_year_formats_are_literal_and_separate_from_source_languages(self):
        rules = [{"value": "[YYYY]", "position": "end"}]
        self.assertEqual(extract_year_from_title("A [2024]", rules), 2024)
        self.assertIsNone(extract_year_from_title("A 2024 version", rules))
        self.assertEqual(clean_lookup_title("A [2024]", year_rules=rules), "A")

    def test_unmarked_title_numbers_are_not_guessed_as_release_years(self):
        for title in (
            "2012",
            "1917",
            "1984",
            "Blade Runner 2049",
            "Class of 1984",
            "2001: A Space Odyssey",
            "Film 2020",
        ):
            with self.subTest(title=title):
                self.assertIsNone(extract_year_from_title(title))
                self.assertEqual(clean_lookup_title(title), title)

    def test_formatted_release_years_preserve_numbers_in_the_title(self):
        for title, expected, year in (
            ("2012 - 2009", "2012", 2009),
            ("2012 (2009)", "2012", 2009),
            ("1917 (2019)", "1917", 2019),
            ("Blade Runner 2049 - 2017", "Blade Runner 2049", 2017),
            ("Class of 1984 [1982]", "Class of 1984", 1982),
        ):
            with self.subTest(title=title):
                self.assertEqual(extract_year_from_title(title), year)
                self.assertEqual(clean_lookup_title(title), expected)

    def test_bare_year_removal_requires_a_known_year_and_keeps_a_real_title(self):
        self.assertEqual(clean_lookup_title("Film 2020", year=2020), "Film")
        for title, year in (
            ("2012", 2012),
            ("(2012)", 2012),
            ("Blade Runner 2049", 2017),
            ("Class of 1984", 1982),
            ("Apollo2012", 2012),
        ):
            with self.subTest(title=title, year=year):
                self.assertEqual(clean_lookup_title(title, year=year), title)

    def test_explicit_year_format_cannot_consume_the_whole_title(self):
        for title in ("(2012)", "[2012]", "- 2012"):
            with self.subTest(title=title):
                self.assertIsNone(extract_year_from_title(title))
                self.assertEqual(clean_lookup_title(title), title)

    def test_invalid_rules_are_rejected(self):
        for function, value in (
            (normalize_title_rules, [""]),
            (normalize_title_rules, ["x"] * 21),
            (normalize_year_rules, ["YYYY YYYY"]),
            (normalize_year_rules, [{"value": "YYYY", "position": "start"}]),
            (normalize_group_title_cleanup, {"pattern": "["}),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                function(value)

    def test_category_regex_is_bounded(self):
        with self.assertRaisesMessage(ValueError, "time limit"):
            clean_lookup_title("a" * 20000 + "!", group_rule={"pattern": "(a+)+$"})


class LibraryTMDBTests(SimpleTestCase):

    def test_details_keep_more_than_two_languages_with_one_request(self):
        client = Client("synthetic-token")
        payload = {
            "id": 123,
            "title": "Film",
            "translations": {
                "translations": [
                    {"iso_639_1": code, "iso_3166_1": region, "data": {"title": title}}
                    for code, region, title in (
                        ("de", "DE", "Film"),
                        ("en", "US", "Movie"),
                        ("es", "ES", "Película"),
                    )
                ]
            },
        }
        with patch.object(client, "get", return_value=payload) as request:
            result = client.details(
                123, "movie", ["de-DE", "en-US", "es-ES"], match_method="manual"
            )
        request.assert_called_once()
        self.assertEqual(list(result["localized"]), ["de-DE", "en-US", "es-ES"])
        self.assertEqual(result["localized"]["es-ES"]["title"], "Película")

    def response(self, status=200, payload=None):
        response = Mock(status_code=status, headers={})
        response.json.return_value = payload or {}
        return response

    def test_api_key_and_bearer_authentication(self):
        for token, header in (("a" * 32, False), ("a" * 100, True)):
            session = Mock()
            session.get.return_value = self.response(payload={"id": 1})
            self.assertEqual(
                Client(token, session=session, min_interval=0).get("movie/1")["id"], 1
            )
            kwargs = session.get.call_args.kwargs
            if header:
                self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {token}")
                self.assertNotIn("api_key", kwargs["params"])
            else:
                self.assertEqual(kwargs["params"]["api_key"], token)
            self.assertEqual(kwargs["timeout"], 15)

    def test_network_errors_never_include_tokens_or_request_urls(self):
        session = Mock()
        session.get.side_effect = requests.RequestException(
            "private URL?api_key=secret"
        )
        with self.assertRaises(TMDBError) as caught:
            Client("secret", session=session).get("movie/1")
        self.assertNotIn("secret", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    @patch("apps.vod.tmdb.time.sleep")
    def test_rate_limit_retries_are_bounded(self, sleep):
        session = Mock()
        response = self.response(429)
        response.headers = {"Retry-After": "1000"}
        response.raise_for_status.side_effect = requests.HTTPError("rate limited")
        session.get.return_value = response
        with self.assertRaises(TMDBError):
            Client("test", session=session, min_interval=0).get("movie/1")
        self.assertEqual(session.get.call_count, 4)
        self.assertTrue(all(call.args[0] <= 10 for call in sleep.call_args_list))

    def test_authentication_errors_are_not_retried(self):
        session = Mock()
        session.get.return_value = self.response(401)
        with self.assertRaises(TMDBAuthenticationError):
            Client("test", session=session).get("movie/1")
        self.assertEqual(session.get.call_count, 1)

    def test_ambiguous_search_never_picks_a_candidate(self):
        client = Client("test")
        with patch.object(
            client,
            "search_candidates",
            return_value=[
                {"id": "1", "title": "Film", "year": 2020},
                {"id": "2", "title": "Film", "year": 2021},
            ],
        ):
            self.assertEqual(
                client.search_outcome("Film", 2020, "movie", ["en-US"]),
                ("", "ambiguous", 2),
            )

    def test_details_keep_localized_titles_and_enrichment_separate(self):
        metadata = normalize_details(
            {
                "id": 1,
                "title": "Film",
                "original_title": "Movie",
                "original_language": "en",
                "release_date": "2020-01-01",
                "translations": {
                    "translations": [
                        {
                            "iso_639_1": "de",
                            "iso_3166_1": "DE",
                            "data": {"title": "Film", "overview": "Beschreibung"},
                        },
                        {
                            "iso_639_1": "en",
                            "iso_3166_1": "US",
                            "data": {"title": "Movie", "overview": "Description"},
                        },
                    ]
                },
                "genres": [{"id": 1, "name": "Drama"}],
                "credits": {"cast": [{"name": "Actor"}]},
            },
            "movie",
            ["de-DE", "en-US"],
            match_method="manual",
        )
        self.assertEqual(metadata["localized"]["de-DE"]["title"], "Film")
        self.assertEqual(metadata["localized"]["en-US"]["title"], "Movie")
        self.assertNotIn("audio_languages", metadata)

    def test_languages_are_an_unordered_set_not_a_preference_list(self):
        for values in (
            ["es-ES", "DE-de", "en-US"],
            ["en-US", "de-DE", "es-ES", "de-DE"],
        ):
            self.assertEqual(normalize_languages(values), ["de-DE", "en-US", "es-ES"])

    def test_library_order_is_separate_from_transport_and_keeps_existing_languages(
        self,
    ):
        languages = ["es-ES", "en-US", "de-DE", "fr-FR", "it-IT", "ja-JP"]
        self.assertEqual(normalize_language_order(languages + ["ES-es"]), languages)
        self.assertEqual(normalize_languages(languages), sorted(languages))

    def test_transport_fallback_is_never_mislabeled_as_the_first_language(self):
        payload = {
            "id": 1,
            "title": "English title",
            "overview": "English overview",
            "original_title": "日本語",
            "original_language": "ja",
        }
        for languages in (["de-DE", "ja-JP", "en-US"], ["ja-JP", "en-US", "de-DE"]):
            document = normalize_details(
                payload, "movie", languages, match_method="manual"
            )
            self.assertEqual(document["original_title"], "日本語")
            self.assertEqual(
                document["localized"]["de-DE"],
                {"title": "", "overview": "", "tagline": ""},
            )
            self.assertEqual(document["localized"]["en-US"]["title"], "English title")
            self.assertEqual(document["localized"]["ja-JP"]["title"], "日本語")
            self.assertEqual(document["response_language"], "en-US")

    def test_details_transport_and_ratings_do_not_depend_on_language_order(self):
        payload = {
            "id": 1,
            "release_dates": {
                "results": [
                    {
                        "iso_3166_1": "DE",
                        "release_dates": [{"type": 3, "certification": "12"}],
                    },
                    {
                        "iso_3166_1": "US",
                        "release_dates": [{"type": 3, "certification": "PG-13"}],
                    },
                ]
            },
        }
        client = Client("synthetic-token")
        for languages in (["de-DE", "en-US"], ["en-US", "de-DE"]):
            with patch.object(client, "get", return_value=payload) as get:
                document = client.details(1, "movie", languages, match_method="manual")
            self.assertEqual(get.call_args.kwargs["language"], "en-US")
            self.assertEqual(document["age_ratings"], {"DE": "12", "US": "PG-13"})
            self.assertEqual(document["age_rating"], "")

    def test_multilingual_search_deduplicates_ids_and_matches_any_translation(self):
        client = Client("synthetic-token")

        def rows(_query, _year, _type, language):
            return [
                {
                    "id": "123",
                    "title": "Der Film" if language == "de-DE" else "The film",
                    "original_title": "Original",
                    "year": 2020,
                }
            ]

        for languages in (["de-DE", "en-US"], ["en-US", "de-DE"]):
            with patch.object(client, "_search_language", side_effect=rows) as search:
                self.assertEqual(
                    client.search_outcome("Der Film", 2020, "movie", languages),
                    ("123", "matched", 1),
                )
                self.assertEqual(search.call_count, 2)

    def test_different_matching_ids_across_languages_remain_ambiguous(self):
        client = Client("synthetic-token")
        with patch.object(
            client,
            "_search_language",
            side_effect=[
                [{"id": "1", "title": "Film", "original_title": "One", "year": 2020}],
                [{"id": "2", "title": "Film", "original_title": "Two", "year": 2020}],
            ],
        ):
            self.assertEqual(
                client.search_outcome("Film", 2020, "movie", ["en-US", "de-DE"]),
                ("", "ambiguous", 2),
            )
