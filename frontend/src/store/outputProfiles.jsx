import { create } from 'zustand';
import api from '../api';

const useOutputProfilesStore = create((set) => ({
  profiles: [],
  isLoading: false,
  error: null,

  fetchProfiles: async () => {
    set({ isLoading: true, error: null });
    try {
      const profiles = await api.getOutputProfiles();
      set({ profiles: profiles, isLoading: false });
    } catch (error) {
      console.error('Failed to fetch output profiles:', error);
      set({ error: 'Failed to load output profiles.', isLoading: false });
    }
  },

  addOutputProfile: (profile) =>
    set((state) => ({
      profiles: [...state.profiles, profile],
    })),

  updateOutputProfile: (profile) =>
    set((state) => ({
      profiles: state.profiles.map((p) => (p.id === profile.id ? profile : p)),
    })),

  removeOutputProfiles: (profileIds) =>
    set((state) => ({
      profiles: state.profiles.filter((p) => !profileIds.includes(p.id)),
    })),
}));

export default useOutputProfilesStore;
