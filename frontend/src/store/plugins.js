import { create } from 'zustand';

const normalizePlugin = (plugin) => {
  if (!plugin || !plugin.key) return plugin;
  const normalized = {
    ...plugin,
    settings: plugin.settings || {},
    fields: plugin.fields || [],
    actions: plugin.actions || [],
    ui_schema: plugin.ui_schema || {},
  };

  const pages = normalized.ui_schema?.pages || [];
  const hasSidebarPage = pages.some(
    (page) => (page?.placement || 'plugin').toLowerCase() === 'sidebar'
  );

  if (hasSidebarPage) {
    const hasField = normalized.fields.some((field) => field.id === 'show_sidebar');
    if (!hasField) {
      normalized.fields = [
        ...normalized.fields,
        {
          id: 'show_sidebar',
          label: 'Show in sidebar',
          type: 'boolean',
          default: true,
          help_text: "Adds this plugin's shortcut to the main sidebar when enabled.",
        },
      ];
    }
    if (normalized.settings.show_sidebar === undefined) {
      normalized.settings = {
        ...normalized.settings,
        show_sidebar: true,
      };
    }
  }

  return normalized;
};

const usePluginsStore = create((set, get) => ({
  plugins: {},
  order: [],
  status: {},
  loading: false,
  error: null,
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  setPlugins: (pluginsList = []) => {
    set((state) => {
      const normalized = {};
      const nextStatus = { ...state.status };
      const order = [];
      pluginsList.forEach((plugin) => {
        if (!plugin?.key) return;
        normalized[plugin.key] = normalizePlugin(plugin);
        order.push(plugin.key);
        if (!nextStatus[plugin.key]) {
          nextStatus[plugin.key] = { lastReloadAt: null, lastError: null };
        }
      });
      // Drop status for removed plugins
      Object.keys(nextStatus).forEach((key) => {
        if (!normalized[key]) {
          delete nextStatus[key];
        }
      });
      return { plugins: normalized, order, status: nextStatus };
    });
  },
  upsertPlugin: (plugin) =>
    set((state) => {
      if (!plugin?.key) return state;
      const status = { ...state.status };
      if (!status[plugin.key]) {
        status[plugin.key] = { lastReloadAt: null, lastError: null };
      }
      return {
        plugins: {
          ...state.plugins,
          [plugin.key]: normalizePlugin({
            ...state.plugins[plugin.key],
            ...plugin,
          }),
        },
        order: state.order.includes(plugin.key)
          ? state.order
          : [...state.order, plugin.key],
        status,
      };
    }),
  removePlugin: (key) =>
    set((state) => {
      if (!state.plugins[key]) return state;
      const nextPlugins = { ...state.plugins };
      delete nextPlugins[key];
      const nextStatus = { ...state.status };
      delete nextStatus[key];
      return {
        plugins: nextPlugins,
        order: state.order.filter((k) => k !== key),
        status: nextStatus,
      };
    }),
  updateSettings: (key, settings) =>
    set((state) => {
      const plugin = state.plugins[key];
      if (!plugin) return state;
      return {
        plugins: {
          ...state.plugins,
          [key]: {
            ...plugin,
            settings: settings || {},
          },
        },
      };
    }),
  updatePluginMeta: (key, patch) =>
    set((state) => {
      const plugin = state.plugins[key];
      if (!plugin) return state;
      return {
        plugins: {
          ...state.plugins,
          [key]: {
            ...plugin,
            ...patch,
          },
        },
      };
    }),
  markPluginsReloaded: () =>
    set((state) => {
      const now = new Date().toISOString();
      const status = { ...state.status };
      state.order.forEach((key) => {
        status[key] = {
          ...(status[key] || {}),
          lastReloadAt: now,
          lastError: null,
        };
      });
      return { status };
    }),
  markPluginsReloadError: (error) =>
    set((state) => {
      const status = { ...state.status };
      state.order.forEach((key) => {
        status[key] = {
          ...(status[key] || {}),
          lastError: error,
        };
      });
      return { status };
    }),
  clearPluginError: (key) =>
    set((state) => {
      const entry = state.status[key];
      if (!entry) return state;
      return {
        status: {
          ...state.status,
          [key]: {
            ...entry,
            lastError: null,
          },
        },
      };
    }),
  movePlugin: (key, direction) =>
    set((state) => {
      const currentIndex = state.order.indexOf(key);
      if (currentIndex === -1) return state;
      const targetIndex = direction === 'up' ? currentIndex - 1 : currentIndex + 1;
      if (targetIndex < 0 || targetIndex >= state.order.length) {
        return state;
      }
      const nextOrder = [...state.order];
      const [item] = nextOrder.splice(currentIndex, 1);
      nextOrder.splice(targetIndex, 0, item);
      return { order: nextOrder };
    }),
  getPlugin: (key) => get().plugins[key],
}));

export default usePluginsStore;
