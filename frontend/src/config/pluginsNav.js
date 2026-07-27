// Unlike settingsNav.js, this can't be a static config — installed plugins
// vary per instance. Sidebar.jsx calls this with the live plugin list (from
// usePluginStore) and the user's pinned-plugin preference (from useAuthStore)
// on every render.

/** Pinned-plugin rows for the primary sidebar, plus a fixed "Find Plugins" entry. */
export const buildPluginsNavEntries = (plugins = [], pinnedKeys = []) => {
  const pinned = plugins
    .filter((p) => !p.missing && pinnedKeys.includes(p.key))
    .map((p) => ({
      id: p.key,
      label: p.name,
      logoUrl: p.logo_url,
      path: `/plugins/${p.key}`,
      updateAvailable: p.install_status === 'update_available',
    }))
    .sort((a, b) => pinnedKeys.indexOf(a.id) - pinnedKeys.indexOf(b.id));

  return {
    findPlugins: { id: '__find-plugins', label: 'Find Plugins', path: '/plugins/browse' },
    pinned,
  };
};
