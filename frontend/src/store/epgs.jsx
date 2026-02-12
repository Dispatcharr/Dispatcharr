import { create } from 'zustand';
import api from '../api';

const determineEPGStatus = (data, currentEpg) => {
  if (data.status) return data.status;
  if (data.action === 'downloading') return 'fetching';
  if (data.action === 'parsing_channels' || data.action === 'parsing_programs')
    return 'parsing';
  if (data.progress === 100) return 'success';
  return currentEpg?.status || 'idle';
};

const useEPGsStore = create((set) => ({
  epgs: {},
  tvgs: [],
  tvgsById: {},
  tvgsLoaded: false,
  isLoading: false,
  error: null,
  refreshProgress: {},

  fetchEPGs: async () => {
    set({ isLoading: true, error: null });
    try {
      const epgs = await api.getEPGs();
      set({
        epgs: epgs.reduce((acc, epg) => {
          acc[epg.id] = epg;
          return acc;
        }, {}),
        isLoading: false,
      });
    } catch (error) {
      console.error('Failed to fetch epgs:', error);
      set({ error: 'Failed to load epgs.', isLoading: false });
    }
  },

  fetchEPGData: async () => {
    set({ isLoading: true, error: null });
    try {
      const tvgs = await api.getEPGData();
      set({
        tvgs: tvgs,
        tvgsById: tvgs.reduce((acc, tvg) => {
          acc[tvg.id] = tvg;
          return acc;
        }, {}),
        tvgsLoaded: true,
        isLoading: false,
      });
    } catch (error) {
      console.error('Failed to fetch tvgs:', error);
      set({
        error: 'Failed to load tvgs.',
        tvgsLoaded: true,
        isLoading: false,
      });
    }
  },

  addEPG: (epg) =>
    set((state) => ({
      epgs: { ...state.epgs, [epg.id]: epg },
    })),

  updateEPG: (epg) =>
    set((state) => {
      // Validate that epg is an object with an id
      if (!epg || typeof epg !== 'object' || !epg.id) {
        console.error('updateEPG called with invalid epg:', epg);
        return state;
      }

      return {
        epgs: { ...state.epgs, [epg.id]: epg },
      };
    }),

  removeEPGs: (epgIds) =>
    set((state) => {
      const updatedEPGs = { ...state.epgs };
      for (const id of epgIds) {
        delete updatedEPGs[id];
      }

      return { epgs: updatedEPGs };
    }),

  updateEPGProgress: (data) =>
    set((state) => {
      // Validate that data is an object with a source
      if (!data || typeof data !== 'object' || !data.source) {
        console.error('updateEPGProgress called with invalid data:', data);
        return state;
      }

      // Early exit if source doesn't exist in our EPGs store
      if (!state.epgs[data.source] && !data.status) {
        return state;
      }

      // Create a new refreshProgress object that includes the current update
      const refreshProgress = {
        ...state.refreshProgress,
        [data.source]: {
          action: data.action,
          progress: data.progress,
          speed: data.speed,
          elapsed_time: data.elapsed_time,
          time_remaining: data.time_remaining,
          status: data.status || 'in_progress',
        },
      };

      // Set the EPG source status based on the update
      // First prioritize explicit status values from the backend
      const status = determineEPGStatus(data, state.epgs[data.source]);

      // Only update epgs object if status or last_message actually changed
      // This prevents unnecessary re-renders on every progress update
      const lastMessage =
        data.status === 'error'
          ? data.error || 'Unknown error'
          : state.epgs[data.source]?.last_message;

      const currentEpg = state.epgs[data.source];
      const shouldUpdateEpg =
        currentEpg &&
        (currentEpg.status !== status ||
          currentEpg.last_message !== lastMessage);

      const epgs = shouldUpdateEpg
        ? {
            ...state.epgs,
            [data.source]: {
              ...currentEpg,
              status,
              last_message: lastMessage,
            },
          }
        : state.epgs;

      return { refreshProgress, epgs };
    }),
}));

export default useEPGsStore;
