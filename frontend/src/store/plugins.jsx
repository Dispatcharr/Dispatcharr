import { create } from 'zustand';
import API from '../api';

export const usePluginStore = create((set, get) => ({
  plugins: [],
  loading: false,
  error: null,

  fetchPlugins: async () => {
    set({ loading: true, error: null });
    try {
      const response = await API.getPlugins();
      set({ plugins: response || [], loading: false });
    } catch (error) {
      set({ error, loading: false });
    }
  },

  updatePlugin: (key, updates) => {
    set((state) => ({
      plugins: state.plugins.map((p) =>
        p.key === key ? { ...p, ...updates } : p
      ),
    }));
  },

  addPlugin: (plugin) => {
    set((state) => ({ plugins: [...state.plugins, plugin] }));
  },

  removePlugin: (key) => {
    set((state) => ({
      plugins: state.plugins.filter((p) => p.key !== key),
    }));
  },

  invalidatePlugins: () => {
    set({ plugins: [] });
    get().fetchPlugins();
  },
}));