"""Unit tests for apps/vod/language.py: the language/quality resolution
precedence."""
from django.test import SimpleTestCase, TestCase

from apps.m3u.models import M3UAccount
from apps.vod.language import (
    apply_language_suffix,
    category_id_for_relation,
    extract_provider_language,
    get_category_metadata,
    invalidate_category_metadata_cache,
    match_quality_from_name,
    quality_rank,
    resolve_episode_relation,
    resolve_language,
    resolve_quality,
    validate_category_custom_properties,
    vod_language_enabled,
)
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODCategory,
)


class ResolveLanguageTests(SimpleTestCase):
    def test_provider_language_wins_over_category(self):
        self.assertEqual(
            resolve_language("es", {"language": "en", "quality": None}), "es"
        )

    def test_falls_back_to_category_language(self):
        self.assertEqual(
            resolve_language(None, {"language": "en", "quality": None}), "en"
        )

    def test_no_category_meta_is_none(self):
        self.assertIsNone(resolve_language(None, None))

    def test_category_without_language_key_is_none(self):
        self.assertIsNone(resolve_language(None, {"quality": "1080p"}))


class MatchQualityFromNameTests(SimpleTestCase):
    def test_4k_and_2160p(self):
        self.assertEqual(match_quality_from_name("Movie 4K Remux"), "4K")
        self.assertEqual(match_quality_from_name("Movie 2160p"), "4K")

    def test_1080p_and_fhd(self):
        self.assertEqual(match_quality_from_name("Movie 1080p"), "1080p")
        self.assertEqual(match_quality_from_name("Movie FHD"), "1080p")

    def test_720p_and_hd(self):
        self.assertEqual(match_quality_from_name("Movie 720p"), "720p")
        self.assertEqual(match_quality_from_name("Movie HD"), "720p")

    def test_480p(self):
        self.assertEqual(match_quality_from_name("Movie 480p"), "480p")

    def test_no_match_returns_none(self):
        self.assertIsNone(match_quality_from_name("Plain Title"))
        self.assertIsNone(match_quality_from_name(""))
        self.assertIsNone(match_quality_from_name(None))

    def test_priority_independent_of_position(self):
        # "HD" appears first in the string, but 4K still wins (matches the
        # pre-existing elif-chain priority, not leftmost-match).
        self.assertEqual(match_quality_from_name("HD Remaster 4K"), "4K")

    def test_case_sensitive_like_the_legacy_branch(self):
        self.assertIsNone(match_quality_from_name("movie 4k"))


class ResolveQualityTests(SimpleTestCase):
    def test_title_match_wins_over_category_default(self):
        self.assertEqual(
            resolve_quality("Movie 1080p", {"quality": "720p"}), "1080p"
        )

    def test_falls_back_to_category_default(self):
        self.assertEqual(resolve_quality("Plain Title", {"quality": "720p"}), "720p")

    def test_none_when_nothing_matches(self):
        self.assertIsNone(resolve_quality("Plain Title", None))
        self.assertIsNone(resolve_quality("Plain Title", {}))


class QualityRankTests(SimpleTestCase):
    def test_known_qualities_rank_best_first(self):
        self.assertLess(quality_rank("4K"), quality_rank("1080p"))
        self.assertLess(quality_rank("1080p"), quality_rank("720p"))
        self.assertLess(quality_rank("720p"), quality_rank("480p"))
        self.assertLess(quality_rank("480p"), quality_rank("SD"))

    def test_unknown_sorts_last(self):
        self.assertGreater(quality_rank(None), quality_rank("SD"))
        self.assertGreater(quality_rank("bogus"), quality_rank("SD"))


class ApplyLanguageSuffixTests(SimpleTestCase):
    def test_appends_uppercased_suffix(self):
        self.assertEqual(apply_language_suffix("Inception", "es"), "Inception [ES]")

    def test_noop_for_unknown_language(self):
        self.assertEqual(apply_language_suffix("Inception", None), "Inception")

    def test_noop_for_blank_name(self):
        self.assertEqual(apply_language_suffix("", "es"), "")
        self.assertIsNone(apply_language_suffix(None, "es"))

    def test_no_double_tag_when_trailing_token_matches(self):
        # Already tagged with exactly this language, case-insensitively,
        # so nothing more is added.
        self.assertEqual(apply_language_suffix("Inception [ES]", "es"), "Inception [ES]")
        self.assertEqual(apply_language_suffix("Casa de Papel (ES)", "es"), "Casa de Papel (ES)")

    def test_mismatched_trailing_token_still_gets_tagged(self):
        # A trailing 2-letter token that isn't the resolved language (another
        # language, or a country-of-origin code like "(UK)") is not language
        # information about this relation's assigned group, so it doesn't
        # suppress the tag. It gets appended alongside instead.
        self.assertEqual(apply_language_suffix("Inception [en]", "es"), "Inception [en] - (ES)")
        self.assertEqual(apply_language_suffix("Inception (EN)", "es"), "Inception (EN) - (ES)")
        self.assertEqual(
            apply_language_suffix("The Apprentice (UK)", "es"), "The Apprentice (UK) - (ES)"
        )

    def test_applied_even_with_a_single_language_group(self):
        # No-op behaviour is only about a pre-existing matching suffix, never
        # about whether the title has one or several language variants.
        self.assertEqual(apply_language_suffix("Solo Title", "en"), "Solo Title [EN]")


class ExtractProviderLanguageTests(SimpleTestCase):
    def test_direct_two_letter_field(self):
        self.assertEqual(extract_provider_language({"language": "ES"}), "es")

    def test_audio_language_field(self):
        self.assertEqual(extract_provider_language({"audio_language": "fr"}), "fr")

    def test_lang_field(self):
        self.assertEqual(extract_provider_language({"lang": "de"}), "de")

    def test_three_letter_iso_639_2_mapped(self):
        self.assertEqual(extract_provider_language({"language": "eng"}), "en")
        self.assertEqual(extract_provider_language({"language": "spa"}), "es")

    def test_unmapped_three_letter_code_is_none(self):
        self.assertIsNone(extract_provider_language({"language": "xyz"}))

    def test_nested_audio_dict(self):
        self.assertEqual(
            extract_provider_language({"audio": {"language": "spa"}}), "es"
        )

    def test_nested_detailed_info_audio(self):
        self.assertEqual(
            extract_provider_language(
                {"detailed_info": {"audio": {"language": "por"}}}
            ),
            "pt",
        )

    def test_no_language_present_returns_none(self):
        self.assertIsNone(extract_provider_language({"name": "Some Movie"}))
        self.assertIsNone(extract_provider_language({}))
        self.assertIsNone(extract_provider_language(None))
        self.assertIsNone(extract_provider_language("not a dict"))


class ValidateCategoryCustomPropertiesTests(SimpleTestCase):
    def test_valid_language_is_lowercased(self):
        result = validate_category_custom_properties({"language": "ES"})
        self.assertEqual(result["language"], "es")

    def test_valid_quality_passes_through(self):
        result = validate_category_custom_properties({"quality": "1080p"})
        self.assertEqual(result["quality"], "1080p")

    def test_null_language_and_quality_are_allowed(self):
        result = validate_category_custom_properties({"language": None, "quality": None})
        self.assertIsNone(result["language"])
        self.assertIsNone(result["quality"])

    def test_invalid_language_rejected(self):
        with self.assertRaises(ValueError):
            validate_category_custom_properties({"language": "eng"})
        with self.assertRaises(ValueError):
            validate_category_custom_properties({"language": "1e"})

    def test_invalid_quality_rejected(self):
        with self.assertRaises(ValueError):
            validate_category_custom_properties({"quality": "4000p"})

    def test_unknown_keys_preserved(self):
        result = validate_category_custom_properties({"language": "en", "custom_flag": True})
        self.assertTrue(result["custom_flag"])

    def test_empty_input_ok(self):
        self.assertEqual(validate_category_custom_properties(None), {})
        self.assertEqual(validate_category_custom_properties({}), {})


class CategoryMetadataTests(TestCase):
    def setUp(self):
        invalidate_category_metadata_cache()
        self.addCleanup(invalidate_category_metadata_cache)
        self.account = M3UAccount.objects.create(
            name="Lang Provider",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        self.category = VODCategory.objects.create(
            name="Spanish Movies", category_type="movie",
        )

    def test_no_category_relations_means_disabled(self):
        self.assertFalse(vod_language_enabled())
        self.assertEqual(get_category_metadata(), {})

    def test_category_with_language_enables_feature(self):
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account,
            category=self.category,
            enabled=True,
            custom_properties={"language": "es"},
        )
        invalidate_category_metadata_cache()

        self.assertTrue(vod_language_enabled())
        meta = get_category_metadata()
        self.assertEqual(
            meta[(self.account.id, self.category.id)],
            {"language": "es", "quality": None},
        )

    def test_category_with_only_quality_does_not_enable_language(self):
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account,
            category=self.category,
            enabled=True,
            custom_properties={"quality": "720p"},
        )
        invalidate_category_metadata_cache()

        self.assertFalse(vod_language_enabled())
        meta = get_category_metadata()
        self.assertEqual(meta[(self.account.id, self.category.id)]["quality"], "720p")

    def test_result_is_cached_until_invalidated(self):
        meta_before = get_category_metadata()
        self.assertEqual(meta_before, {})

        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account,
            category=self.category,
            enabled=True,
            custom_properties={"language": "en"},
        )
        # Stale cache: the new row isn't visible yet.
        self.assertEqual(get_category_metadata(), {})

        invalidate_category_metadata_cache()
        self.assertIn((self.account.id, self.category.id), get_category_metadata())


class CategoryIdForRelationTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Relation Provider", server_url="http://example.com",
            username="user", password="pass", account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        self.category = VODCategory.objects.create(name="A Category", category_type="movie")

    def test_movie_relation_uses_its_own_category(self):
        movie = Movie.objects.create(name="A Movie")
        relation = M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=movie, category=self.category, stream_id="m-1",
        )
        self.assertEqual(category_id_for_relation(relation), self.category.id)

    def test_episode_relation_inherits_its_series_relations_category(self):
        series = Series.objects.create(name="A Series")
        episode = Episode.objects.create(series=series, name="Ep 1")
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=series, category=self.category,
            external_series_id="ext-1",
        )
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=episode, series_relation=series_relation,
            stream_id="e-1",
        )
        self.assertEqual(category_id_for_relation(relation), self.category.id)

    def test_episode_relation_with_no_series_relation_is_none(self):
        series = Series.objects.create(name="Orphan Series")
        episode = Episode.objects.create(series=series, name="Ep 1")
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=episode, series_relation=None, stream_id="e-2",
        )
        self.assertIsNone(category_id_for_relation(relation))


class ResolveEpisodeRelationTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Episode Provider", server_url="http://example.com",
            username="user", password="pass", account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        self.series = Series.objects.create(name="A Series")
        self.episode = Episode.objects.create(series=self.series, name="Ep 1")

    def test_resolves_by_relation_id_first(self):
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=self.episode, stream_id="e-1",
        )
        self.assertEqual(resolve_episode_relation(relation.id).id, relation.id)

    def test_falls_back_to_episode_id_on_miss(self):
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=self.episode, stream_id="e-2",
        )
        # A raw id that isn't a live relation pk but is a live Episode.id.
        self.assertEqual(
            resolve_episode_relation(self.episode.id).episode_id, self.episode.id
        )

    def test_unresolvable_id_returns_none(self):
        self.assertIsNone(resolve_episode_relation(999999))

    def test_non_numeric_id_falls_through_without_raising(self):
        # Both the relation-pk lookup and the Episode.id fallback must
        # tolerate a non-numeric raw_id (mirrors resolve_movie_relation).
        self.assertIsNone(resolve_episode_relation("not-a-number"))
