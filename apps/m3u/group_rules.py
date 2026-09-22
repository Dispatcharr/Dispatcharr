"""Compilation and evaluation of account-scoped group discovery rules."""

from dataclasses import dataclass
import re
from typing import Iterable, Sequence

from .models import M3UGroupRule


@dataclass(frozen=True)
class GroupRuleDecision:
    action: str
    enabled: bool
    matched_rule_id: int | None = None
    metadata_defaults: dict | None = None

    @property
    def ignored(self) -> bool:
        return self.action == M3UGroupRule.Action.IGNORE


def compile_group_rules(rules: Iterable[M3UGroupRule]):
    compiled = []
    for rule in rules:
        flags = 0 if rule.case_sensitive else re.IGNORECASE
        compiled.append(
            (
                rule,
                re.compile(rule.regex_pattern, flags),
                re.compile(rule.exclude_regex_pattern, flags)
                if rule.exclude_regex_pattern
                else None,
            )
        )
    return compiled


def account_group_rules(account, scope: str):
    # Active rules are the configuration. A separate account-level switch only
    # created contradictory states (rules existed but were silently ignored).
    return compile_group_rules(
        account.group_rules.filter(scope=scope, enabled=True).order_by("order", "id")
    )


def evaluate_group_rules(
    compiled_rules,
    *,
    group_name: str,
    item_names: Sequence[str] | None = None,
    default_enabled: bool,
) -> GroupRuleDecision:
    """Return the first matching decision, falling back to account defaults.

    ``item_name`` rules do not match until item names are available. This lets
    callers perform the cheap category-name pass first and a content-aware pass
    when the provider catalog has already been fetched.
    """

    item_names = [str(name or "") for name in (item_names or [])]
    for rule, pattern, exclude_pattern in compiled_rules:
        if rule.match_field == M3UGroupRule.MatchField.GROUP_NAME:
            matched = bool(pattern.search(group_name or ""))
        elif not item_names:
            matched = False
        elif rule.match_mode == M3UGroupRule.MatchMode.ALL:
            matched = all(pattern.search(name) for name in item_names)
        else:
            matched = any(pattern.search(name) for name in item_names)

        if not matched:
            continue

        exclude_targets = (
            [group_name or ""]
            if rule.match_field == M3UGroupRule.MatchField.GROUP_NAME
            else item_names
        )
        if exclude_pattern and any(
            exclude_pattern.search(target) for target in exclude_targets
        ):
            continue

        return GroupRuleDecision(
            action=rule.action,
            enabled=rule.action == M3UGroupRule.Action.ENABLE,
            matched_rule_id=rule.id,
            metadata_defaults=(rule.metadata_defaults or {}).copy(),
        )

    return GroupRuleDecision(
        action=(
            M3UGroupRule.Action.ENABLE
            if default_enabled
            else M3UGroupRule.Action.DISABLE
        ),
        enabled=default_enabled,
    )
