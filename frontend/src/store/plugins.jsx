import { create } from 'zustand';
import API from '../api';

// True if the plugin declares a capability the user hasn't acknowledged yet
// (via the enable confirmation dialog), covering both a brand-new plugin and
// an already-enabled one that added a capability in an update. Unknown
// plugin data (null/undefined) defaults to needing confirmation.
export function needsCapabilityAck(plugin) {
  if (!plugin) return true;
  const acked = new Set(plugin.acknowledged_capabilities || []);
  return (plugin.capabilities || []).some((c) => !acked.has(c.id));
}

export const usePluginStore = create((set, get) => ({
  plugins: [],
  loading: false,
  error: null,

  // Plugin repos (hub)
  repos: [],
  availablePlugins: [],
  reposLoading: false,
  availableLoading: false,
  reposError: null,
  availableError: null,

  // Async plugin action tasks (see WebSocket.jsx plugin_task_progress/
  // plugin_task_complete and PluginDetail.jsx's "Background Tasks" section). Keyed by
  // task_id (globally unique Celery id), so this map can hold entries for
  // more than one plugin at once without collision.
  //
  // A task_id is also durably recorded server-side (apps/plugins/task_history.py,
  // Redis-backed, capped + TTL'd) as soon as it's dispatched, so
  // hydratePluginTasks can rehydrate this map from GET .../tasks/ on mount -
  // history survives a reload or a second browser tab, not just tasks
  // started in this session.
  pluginTasks: {},

  startPluginTask: (taskId, { pluginKey, plugin, actionId, actionLabel }) => {
    set((state) => ({
      pluginTasks: {
        ...state.pluginTasks,
        [taskId]: {
          pluginKey, plugin, actionId, actionLabel,
          status: 'running', percent: null, message: null,
          startedAt: null, updatedAt: null,
        },
      },
    }));
  },

  updatePluginTaskProgress: (taskId, { percent, message, updatedAt }) => {
    set((state) => {
      if (!state.pluginTasks[taskId]) return state;
      return {
        pluginTasks: {
          ...state.pluginTasks,
          [taskId]: {
            ...state.pluginTasks[taskId],
            percent, message,
            startedAt: state.pluginTasks[taskId].startedAt ?? updatedAt,
            updatedAt: updatedAt ?? state.pluginTasks[taskId].updatedAt,
          },
        },
      };
    });
  },

  completePluginTask: (taskId, { status, result, error, updatedAt }) => {
    set((state) => {
      if (!state.pluginTasks[taskId]) return state;
      return {
        pluginTasks: {
          ...state.pluginTasks,
          [taskId]: {
            ...state.pluginTasks[taskId],
            status, result, error,
            startedAt: state.pluginTasks[taskId].startedAt ?? updatedAt,
            updatedAt: updatedAt ?? state.pluginTasks[taskId].updatedAt,
          },
        },
      };
    });
  },

  // Merges server-side task history for one plugin into the live map. Never
  // overwrites an entry already tracked locally, so a slightly-stale fetch
  // can't clobber an in-flight websocket update.
  hydratePluginTasks: (pluginKey, pluginName, tasks) => {
    if (!Array.isArray(tasks) || tasks.length === 0) return;
    set((state) => {
      const next = { ...state.pluginTasks };
      for (const t of tasks) {
        if (next[t.task_id]) continue;
        next[t.task_id] = {
          pluginKey,
          plugin: pluginName,
          actionId: t.action_id,
          actionLabel: t.action_label,
          status: t.status,
          percent: t.percent,
          message: t.message,
          result: t.result,
          error: t.error,
          startedAt: t.startedAt,
          updatedAt: t.updatedAt,
        };
      }
      return { pluginTasks: next };
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

  // First-ever-enable confirmation: a single dialog instance (rendered by
  // <PluginEnableConfirmModal/> in Plugins.jsx and PluginDetail.jsx) shared
  // across every entry point that can flip PluginConfig.enabled, so the
  // capabilities prompt can't drift between them. `requestEnableConfirmation`
  // resolves true/false based on the user's choice in that dialog.
  enableConfirm: { opened: false, plugin: null, resolve: null },

  requestEnableConfirmation: (plugin) => {
    return new Promise((resolve) => {
      set({ enableConfirm: { opened: true, plugin, resolve } });
    });
  },

  resolveEnableConfirmation: (confirmed) => {
    const { resolve } = get().enableConfirm;
    set({ enableConfirm: { opened: false, plugin: null, resolve: null } });
    if (resolve) resolve(confirmed);
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
    set({ reposLoading: true, reposError: null });
    try {
      const repos = await API.getPluginRepos();
      set({ repos: repos || [], reposLoading: false });
    } catch (reposError) {
      set({ reposError, reposLoading: false });
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
    set({ availableLoading: true, availableError: null });
    try {
      const plugins = await API.getAvailablePlugins();
      set({ availablePlugins: plugins || [], availableLoading: false });
    } catch (availableError) {
      set({ availableError, availableLoading: false });
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
