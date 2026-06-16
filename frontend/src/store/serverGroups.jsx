import { create } from 'zustand';
import api from '../api';

const useServerGroupsStore = create((set) => ({
  serverGroups: [],
  isLoading: false,
  error: null,

  fetchServerGroups: async () => {
    set({ isLoading: true, error: null });
    try {
      const serverGroups = await api.getServerGroups();
      set({ serverGroups: serverGroups || [], isLoading: false });
    } catch (error) {
      console.error('Failed to fetch server groups:', error);
      set({ error: 'Failed to load server groups.', isLoading: false });
    }
  },

  addServerGroup: (serverGroup) =>
    set((state) => ({
      serverGroups: [...state.serverGroups, serverGroup],
    })),

  updateServerGroup: (serverGroup) =>
    set((state) => ({
      serverGroups: state.serverGroups.map((group) =>
        group.id === serverGroup.id ? serverGroup : group
      ),
    })),

  removeServerGroups: (serverGroupIds) =>
    set((state) => ({
      serverGroups: state.serverGroups.filter(
        (group) => !serverGroupIds.includes(group.id)
      ),
    })),
}));

export default useServerGroupsStore;
