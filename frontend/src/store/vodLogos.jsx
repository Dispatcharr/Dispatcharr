import { create } from 'zustand';
import api from '../api';

const useVODLogosStore = create((set) => ({
  vodLogos: {},
  logos: [],
  isLoading: false,
  hasLoaded: false,
  error: null,
  totalCount: 0,
  currentPage: 1,
  pageSize: 25,

  setVODLogos: (logos, totalCount = 0) => {
    set({
      vodLogos: logos.reduce((acc, logo) => {
        acc[logo.id] = { ...logo };
        return acc;
      }, {}),
      totalCount,
      hasLoaded: true,
    });
  },

  removeVODLogo: (logoId) =>
    set((state) => {
      const newVODLogos = { ...state.vodLogos };
      delete newVODLogos[logoId];
      return {
        vodLogos: newVODLogos,
        totalCount: Math.max(0, state.totalCount - 1),
      };
    }),

  fetchVODLogos: async (params = {}) => {
    set({ isLoading: true, error: null });
    try {
      const response = await api.getVODLogos(params);

      // Handle both paginated and non-paginated responses
      const logos = Array.isArray(response) ? response : response.results || [];
      const total = response.count || logos.length;

      set({
        vodLogos: logos.reduce((acc, logo) => {
          acc[logo.id] = { ...logo };
          return acc;
        }, {}),
        logos: logos,
        totalCount: total,
        isLoading: false,
        hasLoaded: true,
      });
      return response;
    } catch (error) {
      console.error('Failed to fetch VOD logos:', error);
      set({ error: 'Failed to load VOD logos.', isLoading: false });
      throw error;
    }
  },

  deleteVODLogo: async (logoId) => {
    try {
      await api.deleteVODLogo(logoId);
      set((state) => {
        const newVODLogos = { ...state.vodLogos };
        delete newVODLogos[logoId];
        const newLogos = state.logos.filter((logo) => logo.id !== logoId);
        return {
          vodLogos: newVODLogos,
          logos: newLogos,
          totalCount: Math.max(0, state.totalCount - 1),
        };
      });
    } catch (error) {
      console.error('Failed to delete VOD logo:', error);
      throw error;
    }
  },

  deleteVODLogos: async (logoIds) => {
    try {
      await api.deleteVODLogos(logoIds);
      set((state) => {
        const newVODLogos = { ...state.vodLogos };
        logoIds.forEach((id) => delete newVODLogos[id]);
        const logoIdSet = new Set(logoIds);
        const newLogos = state.logos.filter((logo) => !logoIdSet.has(logo.id));
        return {
          vodLogos: newVODLogos,
          logos: newLogos,
          totalCount: Math.max(0, state.totalCount - logoIds.length),
        };
      });
    } catch (error) {
      console.error('Failed to delete VOD logos:', error);
      throw error;
    }
  },

  cleanupUnusedVODLogos: async () => {
    try {
      const result = await api.cleanupUnusedVODLogos();

      // Refresh the logos after cleanup
      const state = useVODLogosStore.getState();
      await state.fetchVODLogos({
        page: state.currentPage,
        page_size: state.pageSize,
      });

      return result;
    } catch (error) {
      console.error('Failed to cleanup unused VOD logos:', error);
      throw error;
    }
  },

  clearVODLogos: () => {
    set({
      vodLogos: {},
      logos: [],
      hasLoaded: false,
      totalCount: 0,
      error: null,
    });
  },
}));

export default useVODLogosStore;
