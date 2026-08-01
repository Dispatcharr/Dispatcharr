import { create } from 'zustand';
import API from '../api';

// Dismissing a task doesn't delete its history (see dismissPluginTask below);
// it just needs to survive a page reload without a backend write, so we
// track dismissed ids per plugin in localStorage, capped like the Redis-side
// history is (see apps/plugins/task_history.py HISTORY_MAX_ENTRIES).
const DISMISSED_TASKS_STORAGE_PREFIX = 'dispatcharr.dismissedPluginTasks.';
const DISMISSED_TASKS_MAX = 50;

const getDismissedTaskIds = (pluginKey) => {
  try {
    const raw = localStorage.getItem(`${DISMISSED_TASKS_STORAGE_PREFIX}${pluginKey}`);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
};

const addDismissedTaskId = (pluginKey, taskId) => {
  try {
    const ids = Array.from(getDismissedTaskIds(pluginKey));
    ids.push(taskId);
    const capped = ids.slice(-DISMISSED_TASKS_MAX);
    localStorage.setItem(`${DISMISSED_TASKS_STORAGE_PREFIX}${pluginKey}`, JSON.stringify(capped));
  } catch {
    /* localStorage unavailable (e.g. private browsing); dismissal just won't survive reload */
  }
};

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
  // plugin_task_complete and PluginDetail.jsx's "Tasks" section). Keyed by
  // task_id (globally unique Celery id), so this map can hold entries for
  // more than one plugin at once without collision.
  //
  // A task_id is also durably recorded server-side (apps/plugins/task_history.py,
  // Redis-backed, capped + TTL'd) as soon as it's dispatched, so
  // hydratePluginTasks can rehydrate this map from GET .../tasks/ on mount -
  // history survives a reload or a second browser tab, not just tasks
  // started in this session. Dismissal (see dismissPluginTask) is tracked
  // client-side only (localStorage), not sent to the backend.
  pluginTasks: {},

  startPluginTask: (taskId, { pluginKey, plugin, actionId, actionLabel }) => {
    set((state) => ({
      pluginTasks: {
        ...state.pluginTasks,
        [taskId]: {
          pluginKey, plugin, actionId, actionLabel,
          status: 'running', percent: null, message: null,
          startedAt: null, updatedAt: null, dismissed: false,
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

  // Marks a task dismissed (hidden from the live list) without deleting it -
  // history is retained (bounded, see DISMISSED_TASKS_MAX / the backend's
  // HISTORY_MAX_ENTRIES) so it's still reachable via "show dismissed" in the
  // task group modal.
  dismissPluginTask: (taskId) => {
    set((state) => {
      const task = state.pluginTasks[taskId];
      if (!task) return state;
      if (task.pluginKey) addDismissedTaskId(task.pluginKey, taskId);
      return {
        pluginTasks: {
          ...state.pluginTasks,
          [taskId]: { ...task, dismissed: true },
        },
      };
    });
  },

  // Merges server-side task history for one plugin into the live map. Never
  // overwrites an entry already tracked locally, so a slightly-stale fetch
  // can't clobber an in-flight websocket update.
  hydratePluginTasks: (pluginKey, pluginName, tasks) => {
    if (!Array.isArray(tasks) || tasks.length === 0) return;
    const dismissedIds = getDismissedTaskIds(pluginKey);
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
          dismissed: dismissedIds.has(t.task_id),
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
