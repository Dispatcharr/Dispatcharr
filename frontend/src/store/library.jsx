import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import API from '../api';
import useMediaLibraryStore from './mediaLibrary';

const DEFAULT_STAGE = {
  status: 'pending',
  processed: 0,
  total: 0,
};

const toNumber = (value) => {
  const num = Number(value);
  return Number.isFinite(num) ? num : 0;
};

const normalizeStage = (stage = {}, fallback = {}) => {
  const source = {
    ...DEFAULT_STAGE,
    ...fallback,
    ...stage,
  };
  return {
    status: source.status || 'pending',
    processed: toNumber(source.processed),
    total: toNumber(source.total),
  };
};

const normalizeStages = (scan = {}) => {
  const stageFromFields = (prefix) => ({
    status: scan?.[`${prefix}_status`],
    processed: scan?.[`${prefix}_processed`],
    total: scan?.[`${prefix}_total`],
  });

  const sourceStages = scan?.stages || {};
  return {
    discovery: normalizeStage(sourceStages.discovery, stageFromFields('discovery')),
    metadata: normalizeStage(sourceStages.metadata, stageFromFields('metadata')),
    artwork: normalizeStage(sourceStages.artwork, stageFromFields('artwork')),
  };
};

const normalizeScanEntry = (scan) => {
  if (!scan) return scan;
  let processed = scan.processed_files ?? scan.processed;
  if (processed == null && scan.status === 'completed' && scan.total_files != null) {
    processed = scan.total_files;
  }
  if (processed == null) {
    processed = 0;
  }
  processed = toNumber(processed);
  const stages = normalizeStages(scan);
  return {
    ...scan,
    processed,
    processed_files: processed,
    stages,
    discovery_status: stages.discovery.status,
    discovery_processed: stages.discovery.processed,
    discovery_total: stages.discovery.total,
    metadata_status: stages.metadata.status,
    metadata_processed: stages.metadata.processed,
    metadata_total: stages.metadata.total,
    artwork_status: stages.artwork.status,
    artwork_processed: stages.artwork.processed,
    artwork_total: stages.artwork.total,
  };
};

const useLibraryStore = create(
  immer((set, get) => ({
    libraries: [],
    loading: false,
    scans: {},
    scansLoading: false,
    error: null,
    selectedLibraryId: null,
    filters: {
      search: '',
      type: 'all',
      autoScan: 'all',
    },

    setSelectedLibrary: (id) =>
      set((state) => {
        state.selectedLibraryId = id;
      }),

    setFilters: (filters) =>
      set((state) => {
        state.filters = { ...state.filters, ...filters };
      }),

    fetchLibraries: async () => {
      set((state) => {
        state.loading = true;
        state.error = null;
      });
      try {
        const params = new URLSearchParams();
        const { filters } = get();
        if (filters.type !== 'all') {
          params.append('library_type', filters.type);
        }
        if (filters.autoScan !== 'all') {
          params.append('auto_scan_enabled', filters.autoScan === 'enabled');
        }
        if (filters.search) {
          params.append('search', filters.search);
        }
        const data = await API.getMediaLibraries(params);
        set((state) => {
          state.libraries = Array.isArray(data) ? data : data.results || [];
          state.loading = false;
        });
      } catch (error) {
        console.error('Failed to fetch libraries', error);
        set((state) => {
          state.error = 'Failed to load libraries';
          state.loading = false;
        });
      }
    },

    createLibrary: async (payload) => {
      const response = await API.createMediaLibrary(payload);
      set((state) => {
        state.libraries.push(response);
      });
      return response;
    },

    updateLibrary: async (id, payload) => {
      const response = await API.updateMediaLibrary(id, payload);
      set((state) => {
        const index = state.libraries.findIndex((lib) => lib.id === id);
        if (index >= 0) {
          state.libraries[index] = { ...state.libraries[index], ...response };
        }
      });
      return response;
    },

    deleteLibrary: async (id) => {
      let removedLibrary = null;
      let removedScans = null;
      let previousSelectedId = null;
      set((state) => {
        previousSelectedId = state.selectedLibraryId;
        const index = state.libraries.findIndex((lib) => lib.id === id);
        if (index >= 0) {
          removedLibrary = state.libraries[index];
          state.libraries.splice(index, 1);
        }
        if (state.selectedLibraryId === id) {
          state.selectedLibraryId = null;
        }
        if (state.scans[id]) {
          removedScans = state.scans[id];
          delete state.scans[id];
        }
      });
      try {
        await API.deleteMediaLibrary(id);
      } catch (error) {
        set((state) => {
          if (removedLibrary) {
            state.libraries.push(removedLibrary);
            state.libraries.sort((a, b) =>
              (a?.name || '').localeCompare(b?.name || '')
            );
          }
          state.selectedLibraryId = previousSelectedId;
          if (removedScans) {
            state.scans[id] = removedScans;
          }
        });
        throw error;
      }
    },

    purgeCompletedScans: async (options = {}) => {
      const response = await API.purgeLibraryScans(options);
      const statuses =
        Array.isArray(options.statuses) && options.statuses.length > 0
          ? options.statuses
          : ['completed', 'failed', 'cancelled'];
      const libraryFilter =
        options.library !== undefined && options.library !== null
          ? Number(options.library)
          : null;

      set((state) => {
        const keysToUpdate = new Set(['all']);
        if (libraryFilter !== null) {
          keysToUpdate.add(libraryFilter);
        } else {
          Object.keys(state.scans).forEach((key) => keysToUpdate.add(key));
        }

        keysToUpdate.forEach((key) => {
          const list = state.scans[key];
          if (!Array.isArray(list)) return;
          state.scans[key] = list.filter((scan) => {
            const statusMatch = statuses.includes(scan.status);
            const libraryMatch =
              libraryFilter === null || Number(scan.library) === libraryFilter;
            return !(statusMatch && libraryMatch);
          });
        });
      });

      return response;
    },

    triggerScan: async (id, options = {}) => {
      const response = await API.triggerLibraryScan(id, options);
      set((state) => {
        if (!state.scans[id]) {
          state.scans[id] = [];
        }
        const normalized = normalizeScanEntry(response);
        state.scans[id] = [normalized, ...(state.scans[id] || [])];
        state.scans['all'] = [normalized, ...(state.scans['all'] || [])];
      });
      return response;
    },

    fetchScans: async (libraryId, options = {}) => {
      const { background = false } = options;
      if (!background) {
        set((state) => {
          state.scansLoading = true;
        });
      }
      try {
        const params = new URLSearchParams();
        if (libraryId) {
          params.append('library', libraryId);
        }
        const response = await API.getLibraryScans(params);
        set((state) => {
          const payload = Array.isArray(response)
            ? response
            : response.results || [];
          state.scans[libraryId || 'all'] = payload.map((scan) =>
            normalizeScanEntry(scan)
          );
          if (!background) {
            state.scansLoading = false;
          }
        });
      } catch (error) {
        console.error('Failed to fetch scans', error);
        if (!background) {
          set((state) => {
            state.scansLoading = false;
          });
        }
      }
    },

    applyScanUpdate: (event) =>
      set((state) => {
        if (!event?.scan_id) return;
        const scanId = event.scan_id;
        const libraryId = event.library_id || null;

        if (event.media_item) {
          useMediaLibraryStore.getState().upsertItems([event.media_item]);
        }

        const updateList = (list) => {
          const items = list ? [...list] : [];
          const index = items.findIndex((scan) => String(scan.id) === String(scanId));
          const existing = index >= 0 ? items[index] : undefined;
          const processedValue = toNumber(
            event.processed_files ??
              event.processed ??
              existing?.processed_files ??
              existing?.processed ??
              0
          );
          const stageSource = {
            ...(existing || {}),
            ...event,
            stages: event.stages ?? existing?.stages,
          };
          const stages = normalizeStages(stageSource);
          const updatedEntry = {
            id: scanId,
            library: libraryId ?? existing?.library ?? null,
            library_name: event.library_name || existing?.library_name || '',
            status: event.status || 'running',
            summary: event.summary || event.message || items[index]?.summary || '',
            matched_items: event.matched ?? items[index]?.matched_items ?? null,
            unmatched_files: event.unmatched ?? items[index]?.unmatched_files ?? null,
            total_files: event.total ?? event.files ?? items[index]?.total_files ?? null,
            new_files: event.new_files ?? items[index]?.new_files ?? null,
            updated_files: event.updated_files ?? items[index]?.updated_files ?? null,
            removed_files: event.removed_files ?? items[index]?.removed_files ?? null,
            processed: processedValue,
            processed_files: processedValue,
            stages,
            discovery_status: stages.discovery.status,
            discovery_processed: stages.discovery.processed,
            discovery_total: stages.discovery.total,
            metadata_status: stages.metadata.status,
            metadata_processed: stages.metadata.processed,
            metadata_total: stages.metadata.total,
            artwork_status: stages.artwork.status,
            artwork_processed: stages.artwork.processed,
            artwork_total: stages.artwork.total,
            created_at:
              (items[index]?.created_at || new Date().toISOString()),
            finished_at:
              ['completed', 'failed', 'cancelled'].includes(event.status)
                ? new Date().toISOString()
                : items[index]?.finished_at || null,
            updated_at: new Date().toISOString(),
          };

          if (index >= 0) {
            items[index] = normalizeScanEntry({ ...items[index], ...updatedEntry });
          } else {
            items.unshift(normalizeScanEntry(updatedEntry));
          }
          return items;
        };

        const keysToUpdate = [libraryId || 'all'];
        if (libraryId && libraryId !== 'all') {
          keysToUpdate.push('all');
        }

        keysToUpdate.forEach((key) => {
          state.scans[key] = updateList(state.scans[key]);
        });
      }),

    upsertScan: (scan) =>
      set((state) => {
        if (!scan || !scan.id) return;
        const normalized = normalizeScanEntry(scan);
        const targetKeys = new Set(['all']);
        if (normalized.library) {
          targetKeys.add(normalized.library);
        }
        targetKeys.forEach((key) => {
          const items = state.scans[key] ? [...state.scans[key]] : [];
          const index = items.findIndex((entry) => String(entry.id) === String(normalized.id));
          if (index >= 0) {
            items[index] = { ...items[index], ...normalized };
          } else {
            items.unshift(normalized);
          }
          state.scans[key] = items;
        });
      }),

    removeScan: (scanId) =>
      set((state) => {
        if (!scanId) return;
        Object.keys(state.scans).forEach((key) => {
          const list = state.scans[key];
          if (!Array.isArray(list)) return;
          state.scans[key] = list.filter((scan) => String(scan.id) !== String(scanId));
        });
      }),
  }))
);

export default useLibraryStore;
