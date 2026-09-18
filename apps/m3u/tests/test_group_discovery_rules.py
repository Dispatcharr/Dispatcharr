from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.m3u.group_rules import compile_group_rules, evaluate_group_rules
from apps.m3u.models import M3UGroupRule


def rule(
    rule_id,
    pattern,
    action,
    field="group_name",
    mode="any",
    order=0,
    exclude="",
    metadata_defaults=None,
):
    return SimpleNamespace(
        id=rule_id,
        regex_pattern=pattern,
        exclude_regex_pattern=exclude,
        action=action,
        match_field=field,
        match_mode=mode,
        case_sensitive=False,
        order=order,
        metadata_defaults=metadata_defaults or {},
    )


class GroupDiscoveryRuleTests(SimpleTestCase):
    def test_first_matching_rule_wins(self):
        rules = compile_group_rules([
            rule(1, r"adult|xxx", M3UGroupRule.Action.IGNORE),
            rule(2, r"german", M3UGroupRule.Action.ENABLE),
        ])

        decision = evaluate_group_rules(
            rules,
            group_name="German XXX",
            default_enabled=False,
        )

        self.assertTrue(decision.ignored)
        self.assertEqual(decision.matched_rule_id, 1)

    def test_contained_item_rule_supports_any_and_all(self):
        any_rule = compile_group_rules([
            rule(
                3,
                r"avatar",
                M3UGroupRule.Action.ENABLE,
                field="item_name",
                mode="any",
            )
        ])
        all_rule = compile_group_rules([
            rule(
                4,
                r"^de -",
                M3UGroupRule.Action.ENABLE,
                field="item_name",
                mode="all",
            )
        ])

        self.assertTrue(evaluate_group_rules(
            any_rule,
            group_name="Kids",
            item_names=["Other", "Avatar"],
            default_enabled=False,
        ).enabled)
        self.assertFalse(evaluate_group_rules(
            all_rule,
            group_name="Kids",
            item_names=["DE - Avatar", "EN - Avatar"],
            default_enabled=False,
        ).enabled)

    def test_default_is_used_when_no_rule_matches(self):
        decision = evaluate_group_rules(
            compile_group_rules([]),
            group_name="Unmatched",
            default_enabled=True,
        )
        self.assertTrue(decision.enabled)
        self.assertIsNone(decision.matched_rule_id)

    def test_exclusion_expression_vetoes_matching_rule(self):
        compiled = compile_group_rules([
            rule(
                5,
                r"germany",
                M3UGroupRule.Action.ENABLE,
                exclude=r"4k|anime",
            )
        ])

        decision = evaluate_group_rules(
            compiled,
            group_name="GERMANY 4K",
            default_enabled=False,
        )

        self.assertFalse(decision.enabled)
        self.assertIsNone(decision.matched_rule_id)

    def test_rule_carries_initial_vod_metadata(self):
        compiled = compile_group_rules([
            rule(
                6,
                r"multi",
                M3UGroupRule.Action.ENABLE,
                metadata_defaults={
                    "audio_languages": ["ger", "eng"],
                    "resolution": "1080p",
                },
            )
        ])

        decision = evaluate_group_rules(
            compiled,
            group_name="|MULTI| Movies",
            default_enabled=False,
        )

        self.assertEqual(
            decision.metadata_defaults,
            {"audio_languages": ["ger", "eng"], "resolution": "1080p"},
        )
