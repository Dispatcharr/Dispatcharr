import { create } from 'zustand';
import api from '../api';

const useIPAliasesStore = create((set, get) => ({
  aliases: [],
  // Lookup map: ip_address -> alias string
  aliasMap: {},
  isLoading: false,

  fetchAliases: async () => {
    set({ isLoading: true });
    try {
      const aliases = await api.getIPAliases();
      const aliasMap = {};
      if (Array.isArray(aliases)) {
        aliases.forEach((a) => {
          aliasMap[a.ip_address] = a.alias;
        });
      }
      set({ aliases: aliases || [], aliasMap, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  createAlias: async (data) => {
    const response = await api.createIPAlias(data);
    if (response) {
      await get().fetchAliases();
    }
    return response;
  },

  updateAlias: async (id, data) => {
    const response = await api.updateIPAlias(id, data);
    if (response) {
      await get().fetchAliases();
    }
    return response;
  },

  deleteAlias: async (id) => {
    await api.deleteIPAlias(id);
    await get().fetchAliases();
  },

  getAlias: (ip) => {
    return get().aliasMap[ip] || null;
  },
}));

export default useIPAliasesStore;
