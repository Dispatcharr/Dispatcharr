const hasOwn = (object, key) =>
  Object.prototype.hasOwnProperty.call(object || {}, key);

export const profileCategoryRulesConfigured = (profile) => {
  const constraints = profile?.hard_constraints || {};
  return hasOwn(constraints, 'category_import_rules');
};

export const categoryRuleMatches = (rule, row) => {
  if (!rule || rule.enabled === false) return false;
  if (rule.scope !== row.categoryType) return false;
  if (
    rule.m3u_account_id !== null &&
    rule.m3u_account_id !== undefined &&
    rule.m3u_account_id !== '' &&
    String(rule.m3u_account_id) !== String(row.accountId)
  ) {
    return false;
  }
  try {
    const expression = new RegExp(
      rule.regex_pattern || '',
      rule.case_sensitive ? '' : 'i'
    );
    return expression.test(row.categoryName || row.name || '');
  } catch {
    return false;
  }
};

export const firstMatchingCategoryRule = (rules, row) =>
  (rules || []).find((rule) => categoryRuleMatches(rule, row)) || null;

export const resolveProfileCategoryRows = (categories, profile, scope) => {
  const constraints = profile?.hard_constraints || {};
  const configured = profileCategoryRulesConfigured(profile);
  const explicitRules = profile?.category_rules || [];
  const explicitByRelation = new Map(
    explicitRules.map((rule) => [String(rule.category_relation), rule])
  );
  const hasLegacyAllowlist = !configured && explicitRules.length > 0;
  const importRules = constraints.category_import_rules || [];

  return Object.values(categories || {})
    .filter((category) => category.category_type === scope)
    .flatMap((category) =>
      (category.m3u_accounts || [])
        .filter((relation) => relation.enabled !== false)
        .map((relation) => {
          const row = {
            ...category,
            id: String(relation.id),
            category_id: category.id,
            relation_id: relation.id,
            accountId: String(relation.m3u_account),
            accountName: relation.account_name || '',
            categoryName: category.name,
            categoryType: category.category_type,
            metadata_defaults: relation.metadata_defaults || {},
          };
          const explicit = explicitByRelation.get(String(relation.id));
          const matchedRule = configured
            ? firstMatchingCategoryRule(importRules, row)
            : null;
          const enabled = explicit
            ? explicit.enabled !== false
            : !configured
              ? !hasLegacyAllowlist
              : matchedRule
                ? matchedRule.action === 'enable'
                : false;
          return {
            ...row,
            enabled,
            explicit: Boolean(explicit),
            decision_source: explicit
              ? 'Manual override'
              : !configured
                ? hasLegacyAllowlist
                  ? 'Legacy selection'
                  : 'Legacy all categories'
                : matchedRule
                  ? 'Import rule'
                  : 'No matching rule',
            matched_rule_id: matchedRule?.id || '',
          };
        })
    )
    .sort(
      (left, right) =>
        left.accountName.localeCompare(right.accountName) ||
        left.categoryName.localeCompare(right.categoryName)
    );
};
