import { create } from 'zustand';
import api from '../api';

const usePlaylistsStore = create((set) => ({
  playlists: [],
  profiles: {},
  refreshProgress: {},
  isLoading: false,
  error: null,

  profileSearchPreview: '',
  profileResult: '',

  // Add a state variable to trigger M3U editing
  editPlaylistId: null,

  setEditPlaylistId: (id) =>
    set((state) => ({
      editPlaylistId: id,
    })),

  fetchPlaylist: async (id) => {
    set({ isLoading: true, error: null });
    try {
      const playlist = await api.getPlaylist(id);
      set((state) => ({
        playlists: state.playlists.map((p) => (p.id == id ? playlist : p)),
        isLoading: false,
        profiles: {
          ...state.profiles,
          [id]: playlist.profiles,
        },
      }));

      return playlist;
    } catch (error) {
      console.error('Failed to fetch playlists:', error);
      set({ error: 'Failed to load playlists.', isLoading: false });
    }
  },

  fetchPlaylists: async () => {
    set({ isLoading: true, error: null });
    try {
      const playlists = await api.getPlaylists();
      set({
        playlists: playlists,
        isLoading: false,
        profiles: playlists.reduce((acc, playlist) => {
          acc[playlist.id] = playlist.profiles;
          return acc;
        }, {}),
      });
    } catch (error) {
      console.error('Failed to fetch playlists:', error);
      set({ error: 'Failed to load playlists.', isLoading: false });
    }
  },

  addPlaylist: (newPlaylist) =>
    set((state) => ({
      playlists: [...state.playlists, newPlaylist],
      profiles: {
        ...state.profiles,
        [newPlaylist.id]: newPlaylist.profiles,
      },
    })),

  updatePlaylist: (playlist) =>
    set((state) => ({
      playlists: state.playlists.map((pl) =>
        pl.id === playlist.id ? playlist : pl
      ),
      profiles: {
        ...state.profiles,
        [playlist.id]: playlist.profiles,
      },
    })),

  updateProfiles: (playlistId, profiles) =>
    set((state) => ({
      profiles: {
        ...state.profiles,
        [playlistId]: profiles,
      },
    })),

  removePlaylists: (playlistIds) =>
    set((state) => ({
      playlists: state.playlists.filter(
        (playlist) => !playlistIds.includes(playlist.id)
      ),
      // @TODO: remove playlist profiles here
    })),

  setRefreshProgress: (accountIdOrData, data) =>
    set((state) => {
      // If called with two parameters, it's the direct setter
      if (data !== undefined) {
        return {
          refreshProgress: {
            ...state.refreshProgress,
            [accountIdOrData]: data,
          },
        };
      }

      // If called with WebSocket data, preserve 'initializing' status
      // until we get a real progress update from the server
      const accountId = accountIdOrData.account;
      const existingProgress = state.refreshProgress[accountId];

      // Don't replace 'initializing' status with empty/early server messages
      // BUT allow failover updates through (they have failover_url)
      if (
        existingProgress &&
        existingProgress.action === 'initializing' &&
        accountIdOrData.progress === 0 &&
        !accountIdOrData.failover_url
      ) {
        return state; // Keep showing 'initializing' until real progress comes
      }

      return {
        refreshProgress: {
          ...state.refreshProgress,
          [accountId]: accountIdOrData,
        },
      };
    }),

  removeRefreshProgress: (id) =>
    set((state) => {
      const updatedProgress = { ...state.refreshProgress };
      delete updatedProgress[id];

      return {
        refreshProgress: updatedProgress,
      };
    }),

  setProfilePreview: (profileSearchPreview, profileResult) =>
    set((state) => ({
      profileSearchPreview,
      profileResult,
    })),
}));

export default usePlaylistsStore;
