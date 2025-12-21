import { create } from 'zustand';
import API from '../api';

const useLibraryStore = create((set, get) => ({
  libraries: [],
  loading: false,
  error: null,
  scans: {},
  scansLoading: false,

  fetchLibraries: async () => {
    set({ loading: true, error: null });
    try {
      const libraries = await API.getLibraries();
      set({ libraries: Array.isArray(libraries) ? libraries : [], loading: false });
    } catch (error) {
      set({ error: error.message || 'Failed to load libraries.', loading: false });
    }
  },

  createLibrary: async (payload) => {
    const response = await API.createLibrary(payload);
    if (!response) return null;
    set((state) => ({
      libraries: [...state.libraries, response],
    }));
    return response;
  },

  updateLibrary: async (id, payload) => {
    const response = await API.updateLibrary(id, payload);
    if (!response) return null;
    set((state) => ({
      libraries: state.libraries.map((lib) => (lib.id === id ? response : lib)),
    }));
    return response;
  },

  deleteLibrary: async (id) => {
    const success = await API.deleteLibrary(id);
    if (!success) return false;
    set((state) => ({
      libraries: state.libraries.filter((lib) => lib.id !== id),
    }));
    return true;
  },

  fetchScans: async (libraryId = null, { background = false } = {}) => {
    if (!background) {
      set({ scansLoading: true });
    }
    try {
      const scans = await API.getLibraryScans(libraryId);
      const key = libraryId || 'all';
      set((state) => ({
        scans: {
          ...state.scans,
          [key]: Array.isArray(scans) ? scans : [],
        },
        scansLoading: false,
      }));
    } catch (error) {
      if (!background) {
        set({ scansLoading: false });
      }
    }
  },

  triggerScan: async (libraryId, { full = false } = {}) => {
    const scan = await API.triggerLibraryScan(libraryId, { full });
    if (!scan) return null;
    get().upsertScan(scan);
    return scan;
  },

  cancelLibraryScan: async (scanId) => {
    const updated = await API.cancelLibraryScan(scanId);
    if (updated) {
      get().upsertScan(updated);
    }
    return updated;
  },

  deleteLibraryScan: async (scanId) => {
    const success = await API.deleteLibraryScan(scanId);
    if (success) {
      get().removeScan(scanId);
    }
    return success;
  },

  upsertScan: (scan) => {
    if (!scan) return;
    set((state) => {
      const updated = { ...state.scans };
      const keys = [scan.library, 'all'];
      keys.forEach((key) => {
        if (!key) return;
        const list = Array.isArray(updated[key]) ? [...updated[key]] : [];
        const idx = list.findIndex((entry) => entry.id === scan.id);
        if (idx >= 0) {
          list[idx] = scan;
        } else {
          list.unshift(scan);
        }
        updated[key] = list;
      });
      return { scans: updated };
    });
  },

  removeScan: (scanId) => {
    set((state) => {
      const updated = {};
      Object.entries(state.scans).forEach(([key, list]) => {
        updated[key] = Array.isArray(list)
          ? list.filter((scan) => scan.id !== scanId)
          : list;
      });
      return { scans: updated };
    });
  },

  purgeCompletedScans: async ({ library } = {}) => {
    const response = await API.purgeLibraryScans(library);
    if (!response) return null;
    await get().fetchScans(library, { background: true });
    return response;
  },
}));

export default useLibraryStore;
