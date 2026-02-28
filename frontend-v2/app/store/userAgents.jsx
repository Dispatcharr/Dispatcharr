import { create } from "zustand";
import api from "~/lib/api";

const useUserAgentsStore = create((set) => ({
  userAgents: [],
  isLoading: false,
  error: null,

  fetchUserAgents: async () => {
    set({ isLoading: true, error: null });
    try {
      const userAgents = await api.getUserAgents();
      set({ userAgents: userAgents, isLoading: false });
    } catch (error) {
      console.error("Failed to fetch userAgents:", error);
      set({ error: "Failed to load userAgents.", isLoading: false });
    }
  },

  addUserAgent: (userAgent) =>
    set((state) => ({
      userAgents: [...state.userAgents, userAgent],
    })),

  updateUserAgent: (userAgent) =>
    set((state) => ({
      userAgents: state.userAgents.map((ua) =>
        ua.id === userAgent.id ? userAgent : ua,
      ),
    })),

  removeUserAgents: (userAgentIds) =>
    set((state) => ({
      userAgents: state.userAgents.filter(
        (userAgent) => !userAgentIds.includes(userAgent.id),
      ),
    })),
}));

export default useUserAgentsStore;
