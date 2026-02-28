import { create } from "zustand";
import api from "~/lib/api";

const useStreamProfilesStore = create((set) => ({
  profiles: [],
  isLoading: false,
  error: null,

  fetchProfiles: async () => {
    set({ isLoading: true, error: null });
    try {
      const profiles = await api.getStreamProfiles();
      set({ profiles: profiles, isLoading: false });
    } catch (error) {
      console.error("Failed to fetch profiles:", error);
      set({ error: "Failed to load profiles.", isLoading: false });
    }
  },

  addStreamProfile: (profile) =>
    set((state) => ({
      profiles: [...state.profiles, profile],
    })),

  updateStreamProfile: (profile) =>
    set((state) => ({
      profiles: state.profiles.map((prof) =>
        prof.id === profile.id ? profile : prof,
      ),
    })),

  removeStreamProfiles: (propfileIds) =>
    set((state) => ({
      profiles: state.profiles.filter(
        (profile) => !propfileIds.includes(profile.id),
      ),
    })),
}));

export default useStreamProfilesStore;
