import { create } from 'zustand';
import API from '../api';

const defaultFilters = {
  type: 'movie',
  search: '',
};

const DEFAULT_PAGE_SIZE = 60;
const MAX_INCREMENTAL_PAGE_FETCHES = 40;

const pollHandles = new Map();
const inFlightRequests = new Map();
const latestReplaceFetchBySignature = new Map();
let fetchSequence = 0;
let pendingForegroundFetches = 0;
let pendingBackgroundFetches = 0;

const startFetch = (background, set) => {
  const fetchId = ++fetchSequence;
  if (background) {
    pendingBackgroundFetches += 1;
    set({ backgroundLoading: true });
  } else {
    pendingForegroundFetches += 1;
    set({ loading: true });
  }
  return fetchId;
};

const finishFetch = (background, set) => {
  if (background) {
    pendingBackgroundFetches = Math.max(0, pendingBackgroundFetches - 1);
  } else {
    pendingForegroundFetches = Math.max(0, pendingForegroundFetches - 1);
  }
  set({
    loading: pendingForegroundFetches > 0,
    backgroundLoading: pendingBackgroundFetches > 0,
  });
};

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

const mergeForLiveUpdate = (existingItem, incomingItem) => {
  if (!existingItem) return incomingItem;
  const merged = { ...existingItem, ...incomingItem };
  if (incomingItem.watch_progress == null && existingItem.watch_progress !== undefined) {
    merged.watch_progress = existingItem.watch_progress;
  }
  if (incomingItem.watch_summary == null && existingItem.watch_summary !== undefined) {
    merged.watch_summary = existingItem.watch_summary;
  }
  return merged;
};

const extractPaginationPayload = (response) => {
  if (Array.isArray(response)) {
    return {
      items: response,
      count: response.length,
      next: null,
      previous: null,
    };
  }
  const items = Array.isArray(response?.results) ? response.results : [];
  const count = Number.isFinite(response?.count) ? response.count : items.length;
  return {
    items,
    count,
    next: response?.next || null,
    previous: response?.previous || null,
  };
};

const extractPageFromUrl = (pageUrl) => {
  if (!pageUrl) return null;
  try {
    const parsed = new URL(pageUrl, window.location.origin);
    const raw = parsed.searchParams.get('page');
    if (!raw) return null;
    const value = Number(raw);
    return Number.isInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
};

const newestUpdatedAt = (items, fallback = null) => {
  let latest = fallback || null;
  let latestTs = latest ? Date.parse(latest) : 0;
  if (!Number.isFinite(latestTs)) {
    latestTs = 0;
    latest = null;
  }

  items.forEach((item) => {
    const candidate = item?.updated_at;
    if (!candidate) return;
    const candidateTs = Date.parse(candidate);
    if (!Number.isFinite(candidateTs)) return;
    if (candidateTs > latestTs) {
      latestTs = candidateTs;
      latest = candidate;
    }
  });

  return latest;
};

const buildQuerySignature = ({ libraryIds, filters, ordering }) => {
  const normalizedLibraryIds = Array.isArray(libraryIds)
    ? [...libraryIds].map((id) => String(id)).sort().join(',')
    : '';
  const type = filters?.type || '';
  const search = filters?.search || '';
  const orderingKey = ordering || '';
  return `libs:${normalizedLibraryIds}|type:${type}|search:${search}|ordering:${orderingKey}`;
};

const shouldUseReplaceStaleGuard = ({ append, prepend, since, ids }) => {
  return !append && !prepend && !since && !(Array.isArray(ids) && ids.length > 0);
};

const mergePageItems = (
  existingItems,
  incomingItems,
  { append = false, prepend = false } = {}
) => {
  if (!append && !prepend) {
    return [...incomingItems];
  }

  if (prepend) {
    const merged = [];
    const indexById = new Map();

    incomingItems.forEach((item) => {
      if (!item?.id) return;
      const existingIndex = indexById.get(item.id);
      if (existingIndex != null) {
        merged[existingIndex] = item;
        return;
      }
      indexById.set(item.id, merged.length);
      merged.push(item);
    });

    existingItems.forEach((item) => {
      if (!item?.id) return;
      const existingIndex = indexById.get(item.id);
      if (existingIndex != null) {
        // Preserve richer local state when prepending an overlapping page.
        merged[existingIndex] = item;
        return;
      }
      indexById.set(item.id, merged.length);
      merged.push(item);
    });

    return merged;
  }

  const merged = [...existingItems];
  const indexById = new Map();
  merged.forEach((item, index) => {
    if (!item?.id) return;
    indexById.set(item.id, index);
  });

  incomingItems.forEach((item) => {
    if (!item?.id) return;
    const existingIndex = indexById.get(item.id);
    if (existingIndex != null) {
      merged[existingIndex] = item;
      return;
    }
    indexById.set(item.id, merged.length);
    merged.push(item);
  });

  return merged;
};

const upsertItemsIntoList = (existingItems, incomingItems, { prependNew = true } = {}) => {
  const merged = [...existingItems];
  const indexById = new Map();
  merged.forEach((item, index) => {
    if (!item?.id) return;
    indexById.set(item.id, index);
  });

  const newItems = [];
  const newItemIndexById = new Map();

  incomingItems.forEach((item) => {
    if (!item?.id) return;
    const existingIndex = indexById.get(item.id);
    if (existingIndex != null) {
      merged[existingIndex] = item;
      return;
    }

    if (prependNew) {
      const pendingIndex = newItemIndexById.get(item.id);
      if (pendingIndex != null) {
        newItems[pendingIndex] = item;
        return;
      }
      newItemIndexById.set(item.id, newItems.length);
      newItems.push(item);
      return;
    }

    indexById.set(item.id, merged.length);
    merged.push(item);
  });

  return prependNew ? [...newItems, ...merged] : merged;
};

const buildItemsById = (items) => {
  return items.reduce((acc, item) => {
    if (!item?.id) return acc;
    acc[item.id] = item;
    return acc;
  }, {});
};

const useMediaLibraryStore = create((set, get) => ({
  items: [],
  itemsById: {},
  loading: false,
  backgroundLoading: false,
  filters: defaultFilters,
  activeLibraryIds: [],
  selectedLibraryId: null,
  pageSize: DEFAULT_PAGE_SIZE,
  currentPage: 1,
  nextPage: null,
  previousPage: null,
  hasMore: false,
  hasPrevious: false,
  totalCount: 0,
  ordering: '-updated_at',
  activeQuerySignature: '',
  lastUpdatedAt: null,
  activeItem: null,
  activeItemLoading: false,
  activeItemError: null,
  activeProgress: null,
  resumePrompt: null,

  setFilters: (filters) =>
    set((state) => ({ filters: { ...state.filters, ...filters } })),

  setSelectedLibraryId: (id) => set({ selectedLibraryId: id }),

  fetchItems: async (libraryIds = [], options = {}) => {
    const {
      background = false,
      limit = get().pageSize || DEFAULT_PAGE_SIZE,
      ordering = get().ordering || '-updated_at',
      page = 1,
      append = false,
      prepend = false,
      ids = null,
      since = null,
      until = null,
      all = false,
    } = options;

    const resolvedLibraryIds =
      libraryIds === undefined ? get().activeLibraryIds || [] : libraryIds;
    const explicitEmpty = Array.isArray(libraryIds) && libraryIds.length === 0;

    if (!resolvedLibraryIds || resolvedLibraryIds.length === 0) {
      if (explicitEmpty) {
        set({
          items: [],
          itemsById: {},
          loading: false,
          backgroundLoading: false,
          activeLibraryIds: [],
          currentPage: 1,
          nextPage: null,
          previousPage: null,
          hasMore: false,
          hasPrevious: false,
          totalCount: 0,
          activeQuerySignature: '',
          lastUpdatedAt: null,
        });
      }
      return [];
    }

    try {
      const activeFilters = get().filters || defaultFilters;
      const querySignature = buildQuerySignature({
        libraryIds: resolvedLibraryIds,
        filters: activeFilters,
        ordering,
      });
      const guardReplaceResponse = shouldUseReplaceStaleGuard({
        append,
        prepend,
        since,
        ids,
      });
      const params = new URLSearchParams();
      resolvedLibraryIds.forEach((id) => params.append('library', id));
      if (activeFilters.type) {
        params.append('type', activeFilters.type);
      }
      if (activeFilters.search) {
        params.append('search', activeFilters.search);
      }
      if (ordering) {
        params.append('ordering', ordering);
      }
      if (!all && limit) {
        params.append('limit', limit);
      }

      if (since) {
        params.append('updated_after', since);
        if (until) {
          params.append('updated_before', until);
        }
        params.append('page', String(page || 1));
      } else if (Array.isArray(ids) && ids.length > 0) {
        params.append('ids', ids.join(','));
      } else if (!all) {
        params.append('page', String(page || 1));
      }

      const requestKey = `${params.toString()}|bg:${background ? '1' : '0'}`;
      if (inFlightRequests.has(requestKey)) {
        return await inFlightRequests.get(requestKey);
      }

      const requestId = startFetch(background, set);
      if (guardReplaceResponse) {
        latestReplaceFetchBySignature.set(querySignature, requestId);
      }
      const requestPromise = (async () => {
        const response = await API.getMediaItems(params, { raw: true });
        const { items: incomingItems, count, next, previous } = extractPaginationPayload(response);

        if (guardReplaceResponse) {
          const latestForSignature = latestReplaceFetchBySignature.get(querySignature);
          if (latestForSignature != null && requestId < latestForSignature) {
            return get().items || [];
          }
        }
        const stateBeforeMerge = get();
        if (
          stateBeforeMerge.activeQuerySignature
          && stateBeforeMerge.activeQuerySignature !== querySignature
        ) {
          if (append || prepend || since) {
            return stateBeforeMerge.items || [];
          }
        }
        if (append) {
          const expectedPage = stateBeforeMerge.nextPage;
          if (!expectedPage || expectedPage !== page) {
            return stateBeforeMerge.items || [];
          }
        }
        if (prepend) {
          const expectedPage = stateBeforeMerge.previousPage;
          if (!expectedPage || expectedPage !== page) {
            return stateBeforeMerge.items || [];
          }
        }

        if (since) {
          if (incomingItems.length === 0) {
            return [];
          }
          set((state) => {
            const merged = upsertItemsIntoList(state.items, incomingItems, { prependNew: true });
            return {
              items: merged,
              itemsById: buildItemsById(merged),
              activeLibraryIds: resolvedLibraryIds,
              pageSize: limit || state.pageSize,
              ordering,
              activeQuerySignature: querySignature,
              totalCount: Math.max(state.totalCount || 0, merged.length),
              lastUpdatedAt: newestUpdatedAt(incomingItems, state.lastUpdatedAt),
            };
          });
          return incomingItems;
        }

        const existingItems = get().items || [];
        if (
          background
          && !append
          && !prepend
          && incomingItems.length === 0
          && existingItems.length > 0
        ) {
          return existingItems;
        }

        const mergedItems = mergePageItems(existingItems, incomingItems, {
          append,
          prepend,
        });
        const nextPageFromResponse = extractPageFromUrl(next);
        const previousPageFromResponse = extractPageFromUrl(previous);

        set((state) => {
          let nextPage = nextPageFromResponse;
          let previousPage = previousPageFromResponse;

          if (append) {
            previousPage =
              state.previousPage != null ? state.previousPage : previousPageFromResponse;
          } else if (prepend) {
            nextPage = state.nextPage != null ? state.nextPage : nextPageFromResponse;
          }

          return {
            items: mergedItems,
            itemsById: buildItemsById(mergedItems),
            activeLibraryIds: resolvedLibraryIds,
            pageSize: limit || state.pageSize,
            ordering,
            activeQuerySignature: querySignature,
            currentPage: page || 1,
            nextPage,
            previousPage,
            hasMore: Boolean(nextPage),
            hasPrevious: Boolean(previousPage),
            totalCount: Number.isFinite(count) ? count : mergedItems.length,
            lastUpdatedAt: newestUpdatedAt(mergedItems, state.lastUpdatedAt),
          };
        });

        return mergedItems;
      })().finally(() => {
        finishFetch(background, set);
      });

      inFlightRequests.set(requestKey, requestPromise);
      return await requestPromise.finally(() => {
        inFlightRequests.delete(requestKey);
      });
    } catch {
      return [];
    }
  },

  fetchItemsIncremental: async (libraryIds = undefined, options = {}) => {
    const state = get();
    const since = options.since || state.lastUpdatedAt;
    if (!since) {
      return get().fetchItems(libraryIds, {
        ...options,
        background: options.background ?? true,
        ordering: options.ordering || state.ordering || '-updated_at',
        limit: options.limit || state.pageSize || DEFAULT_PAGE_SIZE,
        page: 1,
        append: false,
      });
    }

    const background = options.background ?? true;
    const ordering = options.ordering || state.ordering || '-updated_at';
    const limit = options.limit || Math.max(state.pageSize || DEFAULT_PAGE_SIZE, 120);
    const until = options.until || new Date().toISOString();

    let page = 1;
    let totalFetched = 0;
    while (page <= MAX_INCREMENTAL_PAGE_FETCHES) {
      const incoming = await get().fetchItems(libraryIds, {
        ...options,
        background,
        ordering,
        limit,
        page,
        since,
        until,
      });
      const batchCount = Array.isArray(incoming) ? incoming.length : 0;
      totalFetched += batchCount;
      if (batchCount < limit) {
        break;
      }
      page += 1;
    }

    return totalFetched;
  },

  clearItems: () => {
    latestReplaceFetchBySignature.clear();
    set({
      items: [],
      itemsById: {},
      loading: false,
      backgroundLoading: false,
      activeLibraryIds: [],
      currentPage: 1,
      nextPage: null,
      previousPage: null,
      hasMore: false,
      hasPrevious: false,
      totalCount: 0,
      activeQuerySignature: '',
      lastUpdatedAt: null,
    });
  },

  upsertItems: (items) => {
    if (!Array.isArray(items)) return;
    set((state) => {
      const merged = upsertItemsIntoList(state.items, items, { prependNew: true });
      return {
        items: merged,
        itemsById: buildItemsById(merged),
        totalCount: Math.max(state.totalCount || 0, merged.length),
        lastUpdatedAt: newestUpdatedAt(items, state.lastUpdatedAt),
      };
    });
  },

  upsertLiveItems: (items) => {
    if (!Array.isArray(items)) return;
    set((state) => {
      const itemsById = { ...state.itemsById };
      const mergedItems = [...state.items];
      const mergedIndexById = new Map();
      mergedItems.forEach((entry, index) => {
        if (!entry?.id) return;
        mergedIndexById.set(entry.id, index);
      });
      const newItems = [];
      let activeItem = state.activeItem;
      let activeProgress = state.activeProgress;

      items.forEach((item) => {
        if (!item) return;
        const existing = itemsById[item.id];
        const merged = mergeForLiveUpdate(existing, item);
        itemsById[item.id] = merged;
        const existingIndex = mergedIndexById.get(item.id);
        if (existingIndex != null) {
          mergedItems[existingIndex] = merged;
        } else {
          newItems.push(merged);
        }
        if (activeItem?.id === item.id) {
          activeItem = mergeForLiveUpdate(activeItem, item);
          if (item.watch_progress != null) {
            activeProgress = item.watch_progress;
          }
        }
      });

      const nextItems = newItems.length > 0 ? [...newItems, ...mergedItems] : mergedItems;
      return {
        items: nextItems,
        itemsById,
        activeItem,
        activeProgress,
        totalCount: Math.max(state.totalCount || 0, nextItems.length),
        lastUpdatedAt: newestUpdatedAt(items, state.lastUpdatedAt),
      };
    });
  },

  removeItems: (itemId) => {
    set((state) => {
      const items = state.items.filter((item) => item.id !== itemId);
      const itemsById = { ...state.itemsById };
      delete itemsById[itemId];
      return {
        items,
        itemsById,
        totalCount: Math.max(0, (state.totalCount || 0) - 1),
      };
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
          lastUpdatedAt: newestUpdatedAt([item], state.lastUpdatedAt),
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
        return {
          ...nextState,
          lastUpdatedAt: newestUpdatedAt([item], state.lastUpdatedAt),
        };
      });
      return item;
    } catch {
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
