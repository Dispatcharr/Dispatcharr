export const DEFAULT_CATEGORY_VISIBILITY = Object.freeze({
  enabled: true,
  disabled: true,
  ignored: false,
});

export const categoryStatus = (category) =>
  category.ignored ? 'ignored' : category.enabled ? 'enabled' : 'disabled';

export const matchesCategoryVisibility = (category, visibility) =>
  !!visibility[categoryStatus(category)];

export const categoryStatusPatch = (status) => ({
  enabled: status === 'enabled',
  ignored: status === 'ignored',
});
