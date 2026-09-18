export const flattenVODCategoryRelations = (categories) =>
  Object.values(categories || {})
    .flatMap((category) =>
      (category.m3u_accounts || [])
        .filter((relation) => relation.enabled)
        .map((relation) => ({
          id: String(relation.id),
          accountId: String(relation.m3u_account),
          accountName: relation.account_name,
          categoryName: category.name,
          categoryType: category.category_type,
          metadata: relation.metadata_defaults || {},
        }))
    )
    .sort(
      (left, right) =>
        left.accountName.localeCompare(right.accountName) ||
        left.categoryName.localeCompare(right.categoryName)
    );
