import { create } from 'zustand';
import API from '../api';

export const usePluginStore = create((set, get) => ({
  plugins: [],
  loading: false,
  error: null,

  // Plugin repos (hub)
  repos: [],
  availablePlugins: [],
  reposLoading: false,
  availableLoading: false,

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

  // Repo management
  fetchRepos: async () => {
    set({ reposLoading: true });
    try {
      const repos = await API.getPluginRepos();
      set({ repos: repos || [], reposLoading: false });
    } catch {
      set({ reposLoading: false });
    }
  },

  addRepo: async (data) => {
    const repo = await API.addPluginRepo(data);
    set((state) => ({ repos: [...state.repos, repo] }));
    return repo;
  },

  removeRepo: async (id) => {
    await API.deletePluginRepo(id);
    set((state) => ({ repos: state.repos.filter((r) => r.id !== id) }));
  },

  updateRepo: async (id, data) => {
    const updated = await API.updatePluginRepo(id, data);
    if (updated) {
      set((state) => ({
        repos: state.repos.map((r) => (r.id === id ? updated : r)),
      }));
    }
    return updated;
  },

  refreshRepo: async (id) => {
    const updated = await API.refreshPluginRepo(id);
    if (updated) {
      set((state) => ({
        repos: state.repos.map((r) => (r.id === id ? updated : r)),
      }));
    }
    return updated;
  },

  fetchAvailablePlugins: async () => {
    set({ availableLoading: true });
    try {
      const plugins = await API.getAvailablePlugins();
      set({ availablePlugins: plugins || [], availableLoading: false });
    } catch {
      set({ availableLoading: false });
    }
  },

  installPlugin: async ({ repo_id, slug, version, download_url, sha256, min_dispatcharr_version, max_dispatcharr_version, prerelease }) => {
    const result = await API.installPluginFromRepo({
      repo_id,
      slug,
      version,
      download_url,
      sha256,
      min_dispatcharr_version,
      max_dispatcharr_version,
      prerelease: prerelease === true,
    });
    if (result?.success) {
      await get().fetchAvailablePlugins();
      await get().fetchPlugins();
    }
    return result;
  },
}));
