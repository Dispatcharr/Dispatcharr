import { create } from "zustand";
import api from "~/lib/api";

const useStreamsStore = create((set) => ({
  streams: [],
  count: 0,
  isLoading: false,
  error: null,

  fetchStreams: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await api.getStreams();
      set({
        streams: response.results,
        count: response.count,
        isLoading: false,
      });
    } catch (error) {
      console.error("Failed to fetch streams:", error);
      set({ error: "Failed to load streams.", isLoading: false });
    }
  },

  addStream: (stream) =>
    set((state) => ({
      streams: [...state.streams, stream],
    })),

  updateStream: (stream) =>
    set((state) => ({
      streams: state.streams.map((st) => (st.id === stream.id ? stream : st)),
    })),

  removeStreams: (streamIds) =>
    set((state) => ({
      streams: state.streams.filter((stream) => !streamIds.includes(stream.id)),
    })),
}));

export default useStreamsStore;
