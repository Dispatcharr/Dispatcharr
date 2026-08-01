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

  // Async plugin action tasks (see WebSocket.jsx plugin_task_progress/
  // plugin_task_complete and PluginDetail.jsx's "Running Tasks" section).
  // Keyed by task_id; only tasks started from this UI are tracked here, so
  // progress/complete events for other in-flight tasks (e.g. event-hook
  // dispatches with the dedicated-worker toggle on) are silently ignored.
  pluginTasks: {},

  startPluginTask: (taskId, { plugin, actionLabel }) => {
    set((state) => ({
      pluginTasks: {
        ...state.pluginTasks,
        [taskId]: { plugin, actionLabel, status: 'running', percent: null, message: null },
      },
    }));
  },

  updatePluginTaskProgress: (taskId, { percent, message }) => {
    set((state) => {
      if (!state.pluginTasks[taskId]) return state;
      return {
        pluginTasks: {
          ...state.pluginTasks,
          [taskId]: { ...state.pluginTasks[taskId], percent, message },
        },
      };
    });
  },

  completePluginTask: (taskId, { status, result, error }) => {
    set((state) => {
      if (!state.pluginTasks[taskId]) return state;
      return {
        pluginTasks: {
          ...state.pluginTasks,
          [taskId]: { ...state.pluginTasks[taskId], status, result, error },
        },
      };
    });
  },

  clearPluginTask: (taskId) => {
    set((state) => {
      const { [taskId]: _dropped, ...rest } = state.pluginTasks;
      return { pluginTasks: rest };
    });
  },

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
