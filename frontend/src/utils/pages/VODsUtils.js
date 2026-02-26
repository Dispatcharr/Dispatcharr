export const getCategoryOptions = (categories, filters) => {
  return [
    { value: '', label: 'All Categories' },
    ...Object.values(categories)
      .filter((cat) => {
        if (filters.type === 'movies') return cat.category_type === 'movie';
        if (filters.type === 'series') return cat.category_type === 'series';
        return true; // 'all' shows all
      })
      .map((cat) => ({
        value: `${cat.name}|${cat.category_type}`,
        label: `${cat.name} (${cat.category_type})`,
      })),
  ];
};

export const filterCategoriesToEnabled = (allCategories) => {
  return Object.keys(allCategories).reduce((acc, key) => {
    const enabled = allCategories[key].m3u_accounts.find(
      (account) => account.enabled === true
    );
    if (enabled) {
      acc[key] = allCategories[key];
    }

    return acc;
  }, {});
};
