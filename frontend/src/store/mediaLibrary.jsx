import { create } from 'zustand';
import API from '../api';

const defaultFilters = {
  type: 'movie',
  search: '',
};

const pollHandles = new Map();

const schedulePoll = (itemId, callback, delayMs) => {
  const handle = setTimeout(callback, delayMs);
  pollHandles.set(itemId, handle);
};

const stopPolling = (itemId) => {
  const handle = pollHandles.get(itemId);
  if (handle) {
    clearTimeout(handle);
  }
  pollHandles.delete(itemId);
};

const useMediaLibraryStore = create((set, get) => ({
  items: [],
  itemsById: {},
  loading: false,
  backgroundLoading: false,
  filters: defaultFilters,
  activeLibraryIds: [],
  selectedLibraryId: null,
  activeItem: null,
  activeItemLoading: false,
  activeItemError: null,
  activeProgress: null,
  resumePrompt: null,

  setFilters: (filters) =>
    set((state) => ({ filters: { ...state.filters, ...filters } })),

  setSelectedLibraryId: (id) => set({ selectedLibraryId: id }),

  fetchItems: async (libraryIds = [], { background = false, limit, ordering } = {}) => {
    if (background) {
      set({ backgroundLoading: true });
    } else {
      set({ loading: true });
    }

    try {
      const params = new URLSearchParams();
      libraryIds.forEach((id) => params.append('library', id));
      if (get().filters.type) {
        params.append('type', get().filters.type);
      }
      if (get().filters.search) {
        params.append('search', get().filters.search);
      }
      if (ordering) {
        params.append('ordering', ordering);
      }
      if (limit) {
        params.append('limit', limit);
      }

      const response = await API.getMediaItems(params);
      const items = Array.isArray(response) ? response : response?.results || [];
      const itemsById = items.reduce((acc, item) => {
        acc[item.id] = item;
        return acc;
      }, {});

      set({
        items,
        itemsById,
        loading: false,
        backgroundLoading: false,
        activeLibraryIds: libraryIds,
      });

      return items;
    } catch (error) {
      set({ loading: false, backgroundLoading: false });
      return [];
    }
  },

  upsertItems: (items) => {
    if (!Array.isArray(items)) return;
    set((state) => {
      const itemsById = { ...state.itemsById };
      const merged = [...state.items];

      items.forEach((item) => {
        if (!item) return;
        itemsById[item.id] = item;
        const index = merged.findIndex((entry) => entry.id === item.id);
        if (index >= 0) {
          merged[index] = item;
        } else {
          merged.unshift(item);
        }
      });

      return { items: merged, itemsById };
    });
  },

  removeItems: (itemId) => {
    set((state) => {
      const items = state.items.filter((item) => item.id !== itemId);
      const itemsById = { ...state.itemsById };
      delete itemsById[itemId];
      return { items, itemsById };
    });
  },

  openItem: async (itemId) => {
    if (!itemId) return null;
    set({ activeItemLoading: true, activeItemError: null });
    try {
      const item = await API.getMediaItem(itemId, { suppressErrorNotification: true });
      set((state) => {
        const itemsById = { ...state.itemsById, [item.id]: item };
        const existingIndex = state.items.findIndex((entry) => entry.id === item.id);
        let items = state.items;
        if (existingIndex >= 0) {
          items = [...state.items];
          items[existingIndex] = item;
        } else {
          items = [item, ...state.items];
        }
        return {
          activeItem: item,
          activeItemLoading: false,
          activeItemError: null,
          activeProgress: item?.watch_progress || null,
          items,
          itemsById,
        };
      });
      return item;
    } catch (error) {
      set({ activeItemLoading: false, activeItemError: error?.message || 'Failed to load item.' });
      throw error;
    }
  },

  refreshItem: async (itemId, options = {}) => {
    if (!itemId) return null;
    try {
      const item = await API.getMediaItem(itemId, {
        suppressErrorNotification: true,
        ...options,
      });
      if (!item) return null;
      set((state) => {
        const itemsById = { ...state.itemsById, [item.id]: item };
        const existingIndex = state.items.findIndex((entry) => entry.id === item.id);
        let items = state.items;
        if (existingIndex >= 0) {
          items = [...state.items];
          items[existingIndex] = item;
        } else {
          items = [item, ...state.items];
        }
        const nextState = { items, itemsById };
        if (state.activeItem?.id === item.id) {
          nextState.activeItem = item;
          nextState.activeProgress = item?.watch_progress || null;
        }
        return nextState;
      });
      return item;
    } catch (error) {
      return null;
    }
  },

  pollItem: (itemId, { intervalMs = 4000, timeoutMs = 90000 } = {}) => {
    if (!itemId) return;
    if (pollHandles.has(itemId)) return;
    const baseline = get().itemsById[itemId] || {};
    const baselineSyncedAt = baseline.metadata_last_synced_at || null;
    const baselinePoster = baseline.poster_url || '';
    const baselineBackdrop = baseline.backdrop_url || '';
    const startedAt = Date.now();

    const tick = async () => {
      const item = await get().refreshItem(itemId);
      const timedOut = Date.now() - startedAt > timeoutMs;
      const updated =
        item &&
        ((item.metadata_last_synced_at &&
          item.metadata_last_synced_at !== baselineSyncedAt) ||
          (!baselineSyncedAt && item.metadata_last_synced_at) ||
          item.poster_url !== baselinePoster ||
          item.backdrop_url !== baselineBackdrop);
      if (updated || timedOut || !item) {
        stopPolling(itemId);
        return;
      }
      schedulePoll(itemId, tick, intervalMs);
    };

    schedulePoll(itemId, tick, 0);
  },

  stopPollItem: (itemId) => stopPolling(itemId),

  closeItem: () =>
    set({
      activeItem: null,
      activeItemError: null,
      activeProgress: null,
      resumePrompt: null,
    }),

  setActiveProgress: (progress) => set({ activeProgress: progress }),

  requestResume: (progressId) => {
    const progress = get().activeProgress;
    if (progress && progress.id === progressId) {
      set({ resumePrompt: progress });
    }
  },

  clearResumePrompt: () => set({ resumePrompt: null }),
}));

export default useMediaLibraryStore;
