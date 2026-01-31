import { create } from 'zustand';
import API from '../api';

export const usePluginStore = create((set, get) => ({
  plugins: [],
  loading: false,
  error: null,

  // Navigation items for enabled plugins
  navigation: [],
  navigationLoading: false,

  fetchPlugins: async () => {
    set({ loading: true, error: null });
    try {
      const response = await API.getPlugins();
      set({ plugins: response || [], loading: false });
    } catch (error) {
      set({ error, loading: false });
    }
  },

  fetchNavigation: async () => {
    set({ navigationLoading: true });
    try {
      const navItems = await API.getPluginNavigation();
      set({ navigation: navItems || [], navigationLoading: false });
    } catch (error) {
      console.warn('Failed to fetch plugin navigation:', error);
      set({ navigation: [], navigationLoading: false });
    }
  },

  updatePlugin: (key, updates) => {
    set((state) => ({
      plugins: state.plugins.map((p) =>
        p.key === key ? { ...p, ...updates } : p
      ),
    }));
    // Refresh navigation when a plugin is enabled/disabled
    if ('enabled' in updates) {
      get().fetchNavigation();
    }
  },

  addPlugin: (plugin) => {
    set((state) => ({ plugins: [...state.plugins, plugin] }));
  },

  removePlugin: (key) => {
    set((state) => ({
      plugins: state.plugins.filter((p) => p.key !== key),
    }));
    // Refresh navigation when a plugin is removed
    get().fetchNavigation();
  },

  invalidatePlugins: () => {
    set({ plugins: [] });
    get().fetchPlugins();
    get().fetchNavigation();
  },
}));