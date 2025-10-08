import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import API from '../api';
import useAuthStore from './auth';

const METADATA_REFRESH_COOLDOWN_MS = 60 * 1000;
const metadataRequestCache = new Map();

const shouldRefreshMetadata = (item) => {
  if (!item || !item.id) return false;
  return !item.poster_url || !item.metadata_last_synced_at;
};

const queueMetadataRefresh = (items, { force = false } = {}) => {
  if (!Array.isArray(items) || items.length === 0) return;
  const now = Date.now();
  items.forEach((item) => {
    if (!shouldRefreshMetadata(item)) {
      if (item?.id) {
        metadataRequestCache.delete(item.id);
      }
      return;
    }
    const lastRequested = metadataRequestCache.get(item.id) || 0;
    if (!force && now - lastRequested < METADATA_REFRESH_COOLDOWN_MS) return;
    metadataRequestCache.set(item.id, now);
    API.refreshMediaItemMetadata(item.id).catch((error) => {
      console.debug('Auto metadata refresh failed', error);
      metadataRequestCache.delete(item.id);
    });
  });
};

const initialFilters = {
  type: 'all',
  search: '',
  status: 'all',
  year: '',
};

const getAuthSnapshot = () => {
  const authState = useAuthStore.getState();
  return {
    isAuthenticated: authState.isAuthenticated,
    userId: authState.user?.id ?? null,
  };
};

const resetStateForUser = (state, userId) => {
  state.items = [];
  state.loading = false;
  state.error = null;
  state.total = 0;
  state.activeItem = null;
  state.activeProgress = null;
  state.activeItemLoading = false;
  state.resumePrompt = null;
  state.selectedLibraryId = null;
  state.filters = { ...initialFilters };
  state.ownerUserId = userId ?? null;
};

const useMediaLibraryStore = create(
  immer((set, get) => ({
    ownerUserId: null,
    items: [],
    loading: false,
    error: null,
    total: 0,
    activeItem: null,
    activeProgress: null,
    activeItemLoading: false,
    resumePrompt: null,
    selectedLibraryId: null,
    filters: { ...initialFilters },

    applyUserContext: (userId) =>
      set((state) => {
        const normalized = userId ?? null;
        if (state.ownerUserId === normalized) {
          return;
        }
        resetStateForUser(state, normalized);
      }),

    setFilters: (updated) =>
      set((state) => {
        state.filters = { ...state.filters, ...updated };
      }),

    setSelectedLibraryId: (libraryId) =>
      set((state) => {
        const { userId } = getAuthSnapshot();
        if (state.ownerUserId == null) {
          state.ownerUserId = userId ?? null;
        } else if (userId !== null && state.ownerUserId !== userId) {
          resetStateForUser(state, userId);
        }
        state.selectedLibraryId = libraryId;
      }),

    resetFilters: () =>
      set((state) => {
        state.filters = { ...initialFilters };
      }),

    upsertItems: (itemsToUpsert) =>
      set((state) => {
        const { userId } = getAuthSnapshot();
        if (!userId) {
          return;
        }
        if (state.ownerUserId == null) {
          state.ownerUserId = userId;
        } else if (state.ownerUserId !== userId) {
          return;
        }
        if (!Array.isArray(itemsToUpsert) || itemsToUpsert.length === 0) {
          return;
        }

        const selectedLibraryId = get().selectedLibraryId;
        if (!selectedLibraryId) {
          return;
        }

        const byId = new Map();
        state.items.forEach((item) => {
          byId.set(item.id, item);
        });

        itemsToUpsert.forEach((incoming) => {
          if (!incoming || typeof incoming !== 'object' || !incoming.id) {
            return;
          }
          if (
            incoming.library &&
            Number(incoming.library) !== Number(selectedLibraryId)
          ) {
            return;
          }
          const existing = byId.get(incoming.id) || {};
          byId.set(incoming.id, { ...existing, ...incoming });
        });

        const sorted = Array.from(byId.values()).sort((a, b) => {
          const aTitle = (a.sort_title || a.title || '').toLowerCase();
          const bTitle = (b.sort_title || b.title || '').toLowerCase();
          return aTitle.localeCompare(bTitle);
        });

        state.items = sorted;
        state.total = sorted.length;
      }),

    removeItems: (ids) =>
      set((state) => {
        const { userId } = getAuthSnapshot();
        if (!userId) {
          return;
        }
        if (state.ownerUserId == null) {
          state.ownerUserId = userId;
        } else if (state.ownerUserId !== userId) {
          return;
        }
        const idSet = new Set(Array.isArray(ids) ? ids : [ids]);
        state.items = state.items.filter((item) => !idSet.has(item.id));
        state.total = state.items.length;
      }),

    fetchItems: async (libraryId) => {
      const { isAuthenticated, userId } = getAuthSnapshot();

      if (!libraryId || !isAuthenticated || !userId) {
        set((state) => {
          if (state.ownerUserId == null) {
            state.ownerUserId = userId ?? null;
          } else if (userId !== null && state.ownerUserId !== userId) {
            resetStateForUser(state, userId);
            return;
          }
          state.items = [];
          state.total = 0;
          state.loading = false;
          state.error = null;
        });
        return;
      }

      set((state) => {
        if (state.ownerUserId == null) {
          state.ownerUserId = userId;
        } else if (state.ownerUserId !== userId) {
          resetStateForUser(state, userId);
        }
        state.loading = true;
        state.error = null;
      });

      try {
        const { filters } = get();
        const params = new URLSearchParams();
        params.append('library', libraryId);
        if (filters.type !== 'all') {
          params.append('item_type', filters.type);
        }
        if (filters.status !== 'all') {
          params.append('status', filters.status);
        }
        if (filters.year) {
          params.append('release_year', filters.year);
        }
        if (filters.search) {
          params.append('search', filters.search);
        }
        const response = await API.getMediaItems(params);
        const results = response.results || response;
        const itemsArray = Array.isArray(results) ? results : [];
        set((state) => {
          if (state.ownerUserId !== userId) {
            return;
          }
          state.items = itemsArray;
          state.total = response.count || itemsArray.length || 0;
          state.loading = false;
        });
        queueMetadataRefresh(itemsArray);
      } catch (error) {
        console.error('Failed to fetch media items', error);
        set((state) => {
          if (state.ownerUserId !== userId) {
            return;
          }
          state.error = 'Failed to load media items';
          state.loading = false;
        });
      }
    },

    openItem: async (id) => {
      const { isAuthenticated, userId } = getAuthSnapshot();
      if (!isAuthenticated || !userId) {
        throw new Error('Authentication required');
      }

      set((state) => {
        if (state.ownerUserId == null) {
          state.ownerUserId = userId;
        } else if (state.ownerUserId !== userId) {
          resetStateForUser(state, userId);
        }
        state.activeItemLoading = true;
        state.resumePrompt = null;
        state.activeProgress = null;
      });

      try {
        const response = await API.getMediaItem(id);
        const progress = response.watch_progress || null;
        set((state) => {
          if (state.ownerUserId !== userId) {
            return;
          }
          state.activeItem = response;
          state.activeItemLoading = false;
          state.activeProgress = progress;
        });
        get().upsertItems([response]);
        queueMetadataRefresh([response], { force: true });
        return response;
      } catch (error) {
        console.error('Failed to load media item', error);
        set((state) => {
          if (state.ownerUserId === userId) {
            state.activeItemLoading = false;
          }
        });
        throw error;
      }
    },

    closeItem: () =>
      set((state) => {
        state.activeItem = null;
        state.resumePrompt = null;
        state.activeProgress = null;
      }),

    setActiveProgress: (progress) =>
      set((state) => {
        const { userId } = getAuthSnapshot();
        if (!userId || state.ownerUserId !== userId) {
          return;
        }
        if (state.activeItem) {
          state.activeItem = { ...state.activeItem, watch_progress: progress };
        }
        state.items = state.items.map((item) =>
          item.id === state.activeItem?.id
            ? { ...item, watch_progress: progress }
            : item
        );
        state.activeProgress = progress;
      }),

    requestResume: async (progressId) => {
      const { isAuthenticated, userId } = getAuthSnapshot();
      if (!isAuthenticated || !userId || !progressId) return null;
      try {
        const response = await API.resumeMediaProgress(progressId);
        set((state) => {
          if (state.ownerUserId !== userId) {
            return;
          }
          state.resumePrompt = response;
        });
        return response;
      } catch (error) {
        console.error('Failed to get resume info', error);
        return null;
      }
    },

    clearResumePrompt: () =>
      set((state) => {
        state.resumePrompt = null;
      }),
  }))
);

if (typeof window !== 'undefined') {
  const initialUserId = getAuthSnapshot().userId;
  useMediaLibraryStore.getState().applyUserContext(initialUserId);
  useAuthStore.subscribe(
    (state) => state.user?.id ?? null,
    (userId) => {
      useMediaLibraryStore.getState().applyUserContext(userId);
    }
  );
}

export default useMediaLibraryStore;
