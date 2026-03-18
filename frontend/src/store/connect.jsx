import { create } from 'zustand';
import API from '../api';

const useConnectStore = create((set, get) => ({
  integrations: [],
  isLoading: false,
  error: null,

  fetchIntegrations: async () => {
    set({ isLoading: true, error: null });
    try {
      const list = await API.getConnectIntegrations();
      console.log(list);
      set({
        integrations: Array.isArray(list) ? list : list?.results || [],
        isLoading: false,
      });
    } catch (error) {
      set({ error, isLoading: false });
    }
  },

  addIntegration: (integration) =>
    set((state) => ({ integrations: [...state.integrations, integration] })),

  updateIntegration: (integration) =>
    set((state) => ({
      integrations: state.integrations.map((i) =>
        i.id === integration.id ? integration : i
      ),
    })),

  removeIntegration: (id) =>
    set((state) => ({
      integrations: state.integrations.filter((i) => i.id !== id),
    })),

  updateIntegrationSubscriptions: (id, events) =>
    set((state) => ({
      integrations: state.integrations.map((i) =>
        i.id === id ? { ...i, subscriptions: events } : i
      ),
    })),
}));

export default useConnectStore;
