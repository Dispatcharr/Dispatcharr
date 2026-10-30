"""Removed import results are inert, visible for review, and never reinterpreted."""

import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.m3u.group_rules import compile_group_rules, evaluate_group_rules
from apps.m3u.models import M3UAccount, M3UGroupRule
from apps.vod.models import M3UVODCategoryRelation, VODCategory
from apps.vod.tasks import batch_create_categories


class RetiredRuleResultTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = self.settings(M3U_FILTER_CATALOG_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.account = M3UAccount.objects.create(name="retired-rule-account")
        self.client = APIClient()
        self.client.force_authenticate(
            get_user_model().objects.create_user(
                username="retired-rule-admin", user_level=10
            )
        )
        self.url = f"/api/m3u/accounts/{self.account.pk}/group-rules/"

    def values(self, **overrides):
        return {
            "scope": "movie",
            "match_field": "group_name",
            "regex_pattern": "EN",
            "action": "enable",
            "enabled": True,
            "order": 0,
            "metadata_defaults": {"audio_languages": ["eng"]},
            **overrides,
        }

    def legacy(self, action):
        return M3UGroupRule.objects.create(
            m3u_account=self.account, **self.values(action=action)
        )

    def test_removed_results_cannot_be_created_or_smuggled_into_drafts(self):
        for action in ("keep",):
            for enabled in (True, False):
                values = self.values(action=action, enabled=enabled)
                self.assertEqual(
                    self.client.post(self.url, values, format="json").status_code, 400
                )
                for endpoint in ("preview-draft/", "save-apply/"):
                    response = self.client.post(
                        self.url + endpoint,
                        {
                            "rules": [{"preview_id": "new", **values}],
                            "target_id": "new",
                        },
                        format="json",
                    )
                    self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(self.account.group_rules.exists())

    def test_reading_legacy_rules_reports_paused_without_rewriting_saved_data(self):
        rules = [self.legacy(action) for action in ("keep",)]
        before = list(self.account.group_rules.values())
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["action"] for row in response.data}, {"keep"})
        self.assertTrue(
            all(row["requires_review"] and not row["enabled"] for row in response.data)
        )
        self.assertEqual(list(self.account.group_rules.values()), before)
        decision = evaluate_group_rules(
            compile_group_rules(rules), group_name="EN Movies"
        )
        self.assertFalse(decision.enabled)
        self.assertFalse(decision.ignored)
        self.assertEqual(decision.metadata_defaults, {})

    def test_discovery_keeps_categories_visible_but_does_not_apply_retired_metadata(
        self,
    ):
        for action in ("keep",):
            self.legacy(action)
        known = VODCategory.objects.create(name="EN known", category_type="movie")
        relation = M3UVODCategoryRelation.objects.create(
            category=known, m3u_account=self.account, enabled=True
        )
        result = batch_create_categories(
            [
                {"category_name": "EN known"},
                {"category_name": "EN new"},
            ],
            "movie",
            self.account,
        )
        relation.refresh_from_db()
        self.assertTrue(relation.enabled)
        new = M3UVODCategoryRelation.objects.get(
            category=result["EN new"], m3u_account=self.account
        )
        self.assertFalse(new.enabled)
        self.assertEqual(new.metadata_defaults, {})
        self.assertFalse(result.ignored)

    def test_review_requires_an_explicit_import_result_and_explicit_reactivation(self):
        for action in ("keep",):
            rule = self.legacy(action)
            url = self.url + f"{rule.pk}/"
            response = self.client.patch(url, {"enabled": True}, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                self.client.post(url + "apply/", {}, format="json").status_code, 400
            )
            response = self.client.patch(url, {"action": "disable"}, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertFalse(response.data["enabled"])
            self.assertFalse(response.data["requires_review"])
            self.assertEqual(
                response.data["metadata_defaults"], {"audio_languages": ["eng"]}
            )
            response = self.client.patch(url, {"enabled": True}, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertTrue(response.data["enabled"])
            rule.delete()

    def test_paused_saved_rules_do_not_block_preview_or_apply_of_supported_rules(self):
        paused = self.legacy("keep")
        supported = M3UGroupRule.objects.create(
            m3u_account=self.account, **self.values(order=1)
        )
        category = VODCategory.objects.create(name="EN Movies", category_type="movie")
        relation = M3UVODCategoryRelation.objects.create(
            category=category, m3u_account=self.account, enabled=False
        )
        rows = [
            {
                "preview_id": str(paused.pk),
                **self.values(action="keep", enabled=False),
            },
            {"preview_id": str(supported.pk), **self.values(order=1)},
        ]
        for endpoint in ("preview-draft/", "save-apply/"):
            response = self.client.post(
                self.url + endpoint,
                {"rules": rows, "target_id": str(supported.pk)},
                format="json",
            )
            self.assertEqual(response.status_code, 200, response.data)
        relation.refresh_from_db()
        paused.refresh_from_db()
        self.assertTrue(relation.enabled)
        self.assertEqual(paused.action, "keep")
        self.assertFalse(paused.enabled)

    def test_foreign_or_supported_rule_cannot_claim_a_retired_result(self):
        other = M3UAccount.objects.create(name="foreign-retired-account")
        foreign = M3UGroupRule.objects.create(
            m3u_account=other, **self.values(action="keep")
        )
        supported = M3UGroupRule.objects.create(
            m3u_account=self.account, **self.values()
        )
        for pk in (foreign.pk, supported.pk):
            response = self.client.post(
                self.url + "preview-draft/",
                {
                    "rules": [
                        {
                            "preview_id": str(pk),
                            **self.values(action="keep", enabled=False),
                        }
                    ],
                    "target_id": str(pk),
                },
                format="json",
            )
            self.assertEqual(response.status_code, 400, response.data)

    def test_paused_rule_can_be_reordered_and_deleted(self):
        rule = self.legacy("keep")
        response = self.client.post(
            self.url + "reorder/",
            {"scope": "movie", "ids": [rule.pk], "positions": [3]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        rule.refresh_from_db()
        self.assertEqual((rule.action, rule.order), ("keep", 3))
        self.assertEqual(self.client.delete(self.url + f"{rule.pk}/").status_code, 204)
