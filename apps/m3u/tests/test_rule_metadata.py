"""Metadata rules compose per field without changing import or source identity."""

import tempfile

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.m3u.group_rules import compile_group_rules, evaluate_group_rules
from apps.m3u.models import M3UAccount, M3UGroupRule
from apps.vod.models import Movie, M3UMovieRelation, M3UVODCategoryRelation, VODCategory
from apps.vod.tasks import batch_create_categories


def rule_values(**values):
    return {
        "scope": "movie",
        "match_field": "group_name",
        "match_mode": "any",
        "regex_pattern": "GER",
        "action": "enable",
        "case_sensitive": False,
        "enabled": True,
        "order": 0,
        "metadata_defaults": {"audio_languages": ["ger"]},
        **values,
    }


class MetadataRuleEvaluationTests(SimpleTestCase):
    def evaluate(self, *values):
        rules = [
            M3UGroupRule(id=index + 1, **rule_values(**row))
            for index, row in enumerate(values)
        ]
        return evaluate_group_rules(
            compile_group_rules(rules), group_name="GER ENG 1080p HDR"
        )

    def test_import_and_each_metadata_field_have_independent_first_matches(self):
        decision = self.evaluate(
            {"action": "enable", "metadata_defaults": {}},
            {},
            {"regex_pattern": "1080p", "metadata_defaults": {"resolution": "1080p"}},
            {"regex_pattern": "HDR", "metadata_defaults": {"video_features": ["hdr"]}},
            {"regex_pattern": "ENG", "metadata_defaults": {"audio_languages": ["eng"]}},
            {
                "regex_pattern": "ENG",
                "metadata_defaults": {"subtitle_languages": ["eng"]},
            },
        )
        self.assertTrue(decision.enabled)
        self.assertEqual(decision.matched_rule_id, 1)
        self.assertEqual(
            decision.metadata_defaults,
            {
                "audio_languages": ["ger"],
                "subtitle_languages": ["eng"],
                "resolution": "1080p",
                "video_features": ["hdr"],
            },
        )
        self.assertEqual(decision.fields_for_rule(2), {"audio_languages": ["ger"]})
        self.assertEqual(decision.fields_for_rule(5), {})

    def test_empty_lists_are_explicit_and_disabled_rules_do_not_contribute(self):
        decision = self.evaluate(
            {"enabled": False},
            {"metadata_defaults": {"audio_languages": []}},
            {},
        )
        self.assertTrue(decision.enabled)
        self.assertEqual(decision.matched_rule_id, 2)
        self.assertEqual(decision.metadata_defaults, {"audio_languages": []})

    def test_satisfied_fields_do_not_evaluate_later_expressions(self):
        for action in ("enable", "disable"):
            with self.subTest(action=action):
                rules = [
                    M3UGroupRule(id=1, **rule_values(action=action)),
                    M3UGroupRule(id=2, **rule_values(regex_pattern="(a+)+$")),
                ]
                decision = evaluate_group_rules(
                    compile_group_rules(rules), group_name="GER" + "a" * 10000 + "!"
                )
                self.assertEqual(decision.enabled, action == "enable")
                self.assertEqual(
                    decision.metadata_defaults, {"audio_languages": ["ger"]}
                )


class MetadataRuleApiTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = self.settings(M3U_FILTER_CATALOG_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.account = M3UAccount.objects.create(
            name="metadata-rule-account", account_type="XC"
        )
        self.client = APIClient()
        self.client.force_authenticate(
            get_user_model().objects.create_user(
                username="metadata-rule-admin", user_level=10
            )
        )
        self.url = f"/api/m3u/accounts/{self.account.pk}/group-rules/"

    def category(self, name="GER 1080p", *, account=None, enabled=True):
        category, _ = VODCategory.objects.get_or_create(
            name=name, category_type="movie"
        )
        return M3UVODCategoryRelation.objects.create(
            category=category,
            m3u_account=account or self.account,
            enabled=enabled,
            metadata_defaults={"video_features": ["hdr"]},
        )

    def draft(self, *rows, target="1", endpoint="preview-draft/"):
        return self.client.post(
            self.url + endpoint,
            {
                "rules": [
                    {"preview_id": f"new-{index + 1}", **row}
                    for index, row in enumerate(rows)
                ],
                "target_id": f"new-{target}",
            },
            format="json",
        )

    def test_normalizes_iso_codes_and_rejects_invalid_or_live_metadata(self):
        response = self.client.post(
            self.url,
            rule_values(
                metadata_defaults={
                    "audio_languages": ["de", "deu", "eng"],
                    "resolution": "4K",
                    "video_features": ["HDR", "custom:imax"],
                }
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["metadata_defaults"],
            {
                "audio_languages": ["ger", "eng"],
                "resolution": "2160p",
                "video_features": ["hdr", "custom:imax"],
            },
        )
        for values in (
            {"scope": "live"},
            {"metadata_defaults": {"audio_languages": ["invalid"]}},
            {"metadata_defaults": {"resolution": None}},
            {"action": "ignore"},
            {"metadata_defaults": {"unknown": []}},
        ):
            with self.subTest(values=values):
                response = self.client.post(
                    self.url, rule_values(**values), format="json"
                )
                self.assertEqual(response.status_code, 400, response.data)

    def test_identical_import_predicates_are_rejected_even_for_different_metadata(self):
        first = self.client.post(self.url, rule_values(), format="json")
        second = self.client.post(
            self.url,
            rule_values(metadata_defaults={"resolution": "1080p"}),
            format="json",
        )
        self.assertEqual((first.status_code, second.status_code), (201, 400))
        duplicate = self.client.post(self.url, rule_values(), format="json")
        self.assertEqual(duplicate.status_code, 400)

    def test_preview_contributes_after_import_match_and_is_read_only(self):
        category = self.category()
        response = self.draft(
            rule_values(action="enable", metadata_defaults={}),
            rule_values(regex_pattern="^GER", order=1),
            rule_values(
                regex_pattern="1080p",
                order=2,
                metadata_defaults={"resolution": "1080p"},
            ),
            target="2",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertIsNone(row["would_enable"])
        self.assertEqual(row["metadata_defaults"], {"audio_languages": ["ger"]})
        self.assertEqual(
            response.data["rule_coverage"][1]["field_counts"],
            {"import": 0, "audio_languages": 1},
        )
        category.refresh_from_db()
        self.assertEqual(category.metadata_defaults, {"video_features": ["hdr"]})
        self.assertFalse(M3UGroupRule.objects.exists())

    def test_apply_sets_import_result_and_preserves_other_defaults_and_accounts(self):
        category = self.category(enabled=False)
        other = self.category(
            account=M3UAccount.objects.create(name="other-metadata-account")
        )
        rule = M3UGroupRule.objects.create(m3u_account=self.account, **rule_values())
        response = self.client.post(self.url + f"{rule.pk}/apply/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["enabled"])
        category.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(category.enabled)
        self.assertEqual(
            category.metadata_defaults,
            {
                "audio_languages": ["ger"],
                "video_features": ["hdr"],
            },
        )
        self.assertEqual(other.metadata_defaults, {"video_features": ["hdr"]})
        self.assertEqual(
            response.data["category_updates"][0]["metadata_defaults"],
            {"audio_languages": ["ger"]},
        )

    def test_save_apply_validates_all_targets_and_does_not_apply_covered_fields(self):
        category = self.category()
        response = self.draft(
            rule_values(),
            rule_values(
                order=1,
                regex_pattern="1080p",
                metadata_defaults={
                    "audio_languages": ["eng"],
                    "resolution": "1080p",
                },
            ),
            target="2",
            endpoint="save-apply/",
        )
        self.assertEqual(response.status_code, 200, response.data)
        category.refresh_from_db()
        self.assertEqual(
            category.metadata_defaults,
            {"video_features": ["hdr"], "resolution": "1080p"},
        )
        self.assertEqual(M3UGroupRule.objects.count(), 2)

    def test_discovery_only_populates_new_account_categories_and_source_facts_win(self):
        existing = self.category()
        M3UGroupRule.objects.create(
            m3u_account=self.account, **rule_values(action="enable")
        )
        result = batch_create_categories(
            [
                {"category_name": "GER 1080p"},
                {"category_name": "GER new"},
            ],
            "movie",
            self.account,
        )
        existing.refresh_from_db()
        self.assertEqual(existing.metadata_defaults, {"video_features": ["hdr"]})
        created = M3UVODCategoryRelation.objects.get(
            category=result["GER new"], m3u_account=self.account
        )
        self.assertEqual(created.metadata_defaults, {"audio_languages": ["ger"]})
        source = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            category=created.category,
            movie=Movie.objects.create(name="Shared identity"),
            stream_id="metadata-source",
            declared_metadata={"audio_languages": ["eng"]},
        )
        self.assertEqual(
            source.effective_metadata()["values"]["audio_languages"], ["eng"]
        )
